"""Prepare a placement-specific candidate. GET-only; never activates or moves it."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen

from autonomy import TransferError, check_path, number, wrap
from pick_and_hold.Descend.correction import PROFILE, corrected_plan
from pick_and_hold.Descend.lua_executor import make_plan

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT/'operator_ui/demonstrations/pipeline_feedback_20261017T105725Z/operator_feedback.json'


def adapt_endpoint(original, endpoint, current):
    """Rigid XY/yaw transfer T_current * inv(T_original) * T_taught.

    Same tool and plate geometry required. Preserve measured taught Z on the
    same support surface; do not integrate noisy vision heights or corrections.
    """
    for target in (original, current):
        if target.get('config') != 'Wide' or target.get('converged') is not True:
            raise TransferError('A converged Wide plate reference is required.')
        for key in ('x', 'y', 'rz', 'z_calibrated'):
            number(target.get(key), key)
    goal = {k: number(endpoint.get(k), k) for k in ('X','Y','Z','Rz')}
    angle = math.radians(wrap(current['rz']-original['rz']))
    dx, dy = goal['X']-original['x'], goal['Y']-original['y']
    c, s = math.cos(angle), math.sin(angle)
    return dict(X=current['x']+c*dx-s*dy, Y=current['y']+s*dx+c*dy,
                Z=goal['Z'], Rz=wrap(current['rz']+wrap(goal['Rz']-original['rz'])))


def get(path):
    with urlopen('http://127.0.0.1:5002'+path, timeout=10) as response:
        return json.load(response)


def write_new(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)


def verify_parent(profile, recorded, baseline_raw):
    """Accept an original endpoint or a verified adaptation of that baseline."""
    if recorded['endpoint'] == profile['endpoint']:
        return
    acceptance_path = (ROOT/profile['evidence']).resolve()
    if ROOT not in acceptance_path.parents:
        raise TransferError('Parent evidence is outside the project.')
    acceptance_raw = acceptance_path.read_bytes()
    acceptance = json.loads(acceptance_raw)
    if (hashlib.sha256(acceptance_raw).hexdigest() != profile['evidence_sha256']
            or acceptance.get('visually_accepted') is not True
            or acceptance.get('controller_descent_verified') is not True
            or acceptance.get('endpoint') != profile['endpoint']):
        raise TransferError('Parent adaptation has no verified visual acceptance.')
    trial_path = (ROOT/acceptance['trial']).resolve()
    if trial_path.parent != acceptance_path.parent:
        raise TransferError('Parent trial is outside its evidence folder.')
    trial_raw = trial_path.read_bytes()
    trial = json.loads(trial_raw)
    evidence = json.loads((acceptance_path.parent/'evidence.json').read_bytes())
    if (hashlib.sha256(trial_raw).hexdigest() != acceptance['trial_sha256']
            or trial.get('status') != 'completed_awaiting_visual_inspection'
            or trial.get('result', {}).get('ok') is not True
            or evidence.get('baseline_sha256') != hashlib.sha256(baseline_raw).hexdigest()
            or evidence.get('original_target') != recorded['original_target']
            or evidence.get('original_endpoint') != recorded['endpoint']
            or adapt_endpoint(recorded['original_target'], recorded['endpoint'],
                              evidence['current_target']) != profile['endpoint']):
        raise TransferError('Parent adaptation does not match the successful baseline.')


def prepare(*, centering=None):
    state, cfg, seq = get('/state'), get('/robot_params'), get('/seq')
    band = get('/torque_threshold')['band_counts']
    robot, target = state['robot'], state['target']
    if (state['sequence']['active'] or not robot.get('connected') or not robot.get('ok')
            or robot.get('errors') or not state['envelope']['enabled']):
        raise TransferError('Healthy stationary feedback with workspace enabled is required.')
    if seq['name'] not in ('align','researcher_align') or seq['state'] != 'done' or not seq['result'].get('ok'):
        raise TransferError('A completed Align is required to prepare this candidate.')
    if seq['target'] != target:
        raise TransferError('Alignment and current vision references differ.')
    baseline_raw, profile_raw = BASELINE.read_bytes(), PROFILE.read_bytes()
    baseline, profile = json.loads(baseline_raw), json.loads(profile_raw)
    completed = [r for r in baseline['sequence_outcomes'] if r['sequence']=='researcher_descend'
                 and r['state']=='done' and r['result'].get('ok')]
    if len(completed) != 1:
        raise TransferError('Expected one verified baseline descent.')
    recorded = completed[0]['result']['descent_correction']
    verify_parent(profile, recorded, baseline_raw)
    goal = adapt_endpoint(recorded['original_target'], recorded['endpoint'], target)
    if centering is not None:
        # Commissioning-only offset anchored to the measured pose. Do not also
        # add a new vision-placement correction to the same physical plate.
        measured = centering['measured_pose']
        if any(abs(number(measured.get(k),k)-profile['endpoint'][k]) > .01
               for k in ('X','Y','Z','Rz')):
            raise TransferError('Gap observation does not match the accepted endpoint.')
        delta = {k:number(centering['delta_base_mm'].get(k),k) for k in ('X','Y')}
        if not 0 < math.hypot(delta['X'],delta['Y']) <= 1.0:
            raise TransferError('Centering candidate must be within the measured 1 mm range.')
        goal = dict(profile['endpoint'])
        goal.update(X=goal['X']+delta['X'],Y=goal['Y']+delta['Y'])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = ROOT/'operator_ui/reports/descent_trials'/('adapted_'+stamp)
    folder.mkdir(parents=True, exist_ok=False)
    evidence = dict(schema='cephla.adapted-descent-evidence.v1', created_at=stamp,
        baseline_path=str(BASELINE.relative_to(ROOT)),
        baseline_sha256=hashlib.sha256(baseline_raw).hexdigest(),
        parent_profile_sha256=hashlib.sha256(profile_raw).hexdigest(),
        original_target=recorded['original_target'], original_endpoint=recorded['endpoint'],
        current_target=target, endpoint=goal,
        method='Rigid XY/yaw transfer of successful correction; same-surface taught Z retained.',
        assumptions=['Same plate/tool geometry', 'Same support surface and plate height'],
        hardware_validated=False, execution_authorized=False)
    if centering is not None:
        evidence.update(method='Measured-pose centering offset; fresh calibration verifies plate direction and placement. No additional placement transform.',
                        operator_centering=centering)
    evidence_path=folder/'evidence.json'
    write_new(evidence_path,evidence)
    candidate=deepcopy(profile)
    candidate.update(id='two_disk_adapted_'+stamp, endpoint=goal,
        scope='Candidate for this recorded current plate placement only; supervised trial pending.',
        evidence=evidence_path.relative_to(ROOT).as_posix(),
        evidence_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        note='Prepared offline, not activated. No grip or physical clearance implied.')
    candidate_path=folder/'candidate_profile.json'
    write_new(candidate_path,candidate)
    write_new(folder/'previous_profile.json',profile)
    envelope={a:[state['envelope'][a]['min'],state['envelope'][a]['max']] for a in ('X','Y','Z')}
    pose,joints=robot['pose_mm'],robot['joints']
    plan=corrected_plan(pose,joints,target,cfg,envelope,band,profile_path=candidate_path)
    checked=[]
    previous,q=pose,dict(joints)
    for point in [*plan['legs'],goal]:
        next_q=check_path(previous,point,q,cfg,envelope)
        next_q['J1']=joints['J1']+point['Z']-pose['Z']
        if not 0<=next_q['J1']<=400 or abs(next_q['J3'])>180:
            raise TransferError('Joint travel exceeds configured limits.')
        checked.append(dict(pose=point,joints=next_q))
        previous,q=point,next_q
    hover_q=checked[-2]['joints'] if len(checked)>1 else joints
    lua=make_plan(plan['hover'],hover_q,plan['target'],cfg,envelope,band)
    # Re-read state to avoid publishing a review assembled across concurrent motion.
    latest=get('/state')
    if latest['sequence']['active'] or latest['target']!=target:
        raise TransferError('State changed while preparing; candidate not reviewed.')
    for key in ('X','Y','Z','Rz'):
        delta=latest['robot']['pose_mm'][key]-pose[key]
        if key=='Rz': delta=wrap(delta)
        if abs(delta)>.05:
            raise TransferError('Arm moved during review.')
    report=dict(schema='cephla.adapted-descent-review.v1', state=state, config=cfg,
        band=band, envelope=envelope, candidate_profile=str(candidate_path.relative_to(ROOT)),
        candidate_sha256=hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        plan=plan, checked=checked, lua_plan=lua, ik_and_limits_passed=True,
        activated=False, hardware_validated=False, execution_authorized=False,
        inspection='Stop with claws open; inspect jaw centering/height before any grip.',
        requires=['Same support surface confirmed','Empty gripper, clear correction sweep and descent',
                  'Arm released, hands clear, E-stop supervised','Fresh matching Align at execution'])
    write_new(folder/'review.json',report)
    print(json.dumps(dict(review=str(folder/'review.json'), endpoint=goal, hover=plan['hover'],
        adjustment={k:goal[k]-pose[k] for k in ('X','Y','Rz')},
        ik_and_limits_passed=True, activated=False, approach_speed=137, final_speed=5),indent=2))
    return folder/'review.json'


if __name__=='__main__':
    prepare()
