"""One supervised release and empty return from the November 8 Hamilton seat."""
from gripper_closure import POLICY, closure_commands
import hashlib
import json
import math
import time
from copy import deepcopy

from autonomy import TransferError, check_path
import hamilton_reteach_trial as taught
from scope_step_trial import near, preflight

# Fresh evidence for the operator-requested faster hover ascent; preserve the
# accepted [5, 5, 137, 137] trial unchanged.
OUTPUT = taught.PLAN.with_name('release_empty_home_speed137_repeat01_20261108.json')
SPEEDS = (5, 137, 137, 137)


def output_path(trial_id=None):
    if trial_id is None:return OUTPUT
    return taught.output_path(False,trial_id).with_name('handling_'+trial_id+'.json')


def reference(forward_trial_id=None):
    plan = taught.reference()
    raw = taught.output_path(False,forward_trial_id).read_bytes()
    receipt = json.loads(raw)
    if (receipt.get('status') != 'completed'
            or receipt.get('plan', {}).get('candidate_sha256') != taught.SHA
            or receipt.get('result', {}).get('ok') is not True):
        raise TransferError('Completed matching Hamilton approach required.')
    reverse = deepcopy(plan['routes']['reverse'])
    route = [reverse[0], {**reverse[0], 'Z': round(reverse[0]['Z'] + 5, 2)}] + reverse[1:]
    return plan, receipt, hashlib.sha256(raw).hexdigest(), route


def validate_route(start, points):
    _, _, _, route = reference()
    for index in range(4):
        if points == [route[index + 1]]:
            near(start, route[index], .05)
            return index
    raise TransferError('Only the exact Hamilton release-return leg is allowed.')


def check_route(start, points, joints, cfg, envelope):
    index = validate_route(start, points)
    plan, _, _, route = reference()
    if any(value != plan['cfg'].get(key) for key,value in cfg.items()) or {k:list(v) for k,v in envelope.items()} != plan['parent']['envelope']:
        raise TransferError('Hamilton release settings changed.')
    # This exact local lift/exit is a station-specific route, not a workspace change.
    # Derive every starting joint configuration from the measured taught seat.
    q = deepcopy(plan['measured_joints'])
    offset = q['J1'] - plan['measured_pose']['Z']
    expected = [deepcopy(q)]
    for a, b in zip(route, route[1:]):
        q = check_path(a, b, q, cfg, None)
        q['J1'] = b['Z'] + offset
        if not 0 <= q['J1'] <= 400 or abs(q['J3']) > 180:
            raise TransferError('Hamilton release exceeds joint travel.')
        expected.append(deepcopy(q))
    if any(abs(joints[k] - expected[index][k]) > .5 for k in ('J1','J2','J3','J4')):
        raise TransferError('Hamilton release starting joint configuration changed.')
    result = check_path(start, points[0], joints, cfg, None)
    result['J1'] = joints['J1'] + points[0]['Z'] - start['Z']
    if not 0 <= result['J1'] <= 400 or abs(result['J3']) > 180:
        raise TransferError('Hamilton release exceeds live joint travel.')
    return result


def e1(state):
    value = state.get('external_axes', {}).get('E1')
    if type(value) not in (int, float) or not math.isfinite(value):
        raise TransferError('Fresh claw position unavailable.')
    return value


def review(service, cfg, trial_id=None, forward_trial_id=None, operation='release'):
    if operation not in ('release','pickup'):raise TransferError('Unknown Hamilton handling operation')
    if operation=='pickup' and (trial_id is None or forward_trial_id is None):
        raise TransferError('Pickup requires fresh handling and approach IDs')
    if output_path(trial_id).exists():
        raise TransferError('Hamilton release already attempted; inspect before any retry.')
    plan, receipt, digest, route = reference(forward_trial_id)
    state = preflight(service)
    near(state['pose_mm'], route[0], .05)
    if abs(e1(state) - e1(receipt['final_robot'])) > .1:
        raise TransferError('Grip changed since Hamilton arrival.')
    if operation=='pickup' and abs(e1(state)-7)>.15:
        raise TransferError('Hamilton pickup requires empty jaws at 7 mm')
    q = state['joints']
    for a, b in zip(route, route[1:]):
        q = check_route(a, [b], q, cfg, service.envelope)
    from trajectory_queue import LuaTrajectory, travel_program_blocker
    refusal = travel_program_blocker(LuaTrajectory(service).capability(), 137)
    if refusal:
        raise TransferError(refusal)
    return dict(closure_policy=POLICY,candidate_sha256=taught.SHA, forward_sha256=digest,
                route=route, speeds=list(SPEEDS), cfg=cfg, e1=e1(state),
                trial_id=trial_id,forward_trial_id=forward_trial_id,operation=operation)


def execute(run, service, cfg, approved):
    fresh = review(service, cfg,approved.get('trial_id'),approved.get('forward_trial_id'),approved.get('operation','release'))
    output=output_path(fresh['trial_id']);pickup=fresh['operation']=='pickup'
    if any(fresh[k] != approved.get(k) for k in fresh if k != 'e1') or abs(fresh['e1'] - approved['e1']) > .05:
        raise TransferError('Hamilton release plan changed before dispatch.')
    record = dict(status='started', plan=fresh, started_at=time.time(),
                  authorization=('Operator requested supervised pickup at the current taught Hamilton seat, approach at10 and final1mm close at5 to3.9 mm, lift 5 mm at speed 5, then loaded Home.' if pickup else 'Operator confirmed plate fully supported at Hamilton and claws clear to open to 7 mm and lift; requested empty Home.'),
                  before=service.status(), samples=[], steps=[], jaw_commands=[],operator_acceptance=None)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2)

    def save():
        output.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')

    def healthy(expected=None):
        if run.stopped():
            raise TransferError('Hamilton release stopped; no next action.')
        state = preflight(service)
        _, _, digest, _ = reference(fresh['forward_trial_id'])
        if digest != fresh['forward_sha256']:
            raise TransferError('Hamilton approach receipt changed.')
        if expected is not None and abs(e1(state) - expected) > .1:
            raise TransferError('Claw feedback changed during empty return.')
        return state

    try:
        state = healthy(fresh['e1'])
        near(state['pose_mm'], fresh['route'][0], .05)
        commands=closure_commands(7,3.9) if pickup else [dict(target_e1_mm=7,speed=5)]
        for command in commands:
            target,speed=command['target_e1_mm'],command['speed']
            state=healthy();near(state['pose_mm'],fresh['route'][0],.05)
            run.say(f'Hamilton {fresh["operation"]}: jaws to {target} mm at speed {speed}.')
            response = service.move_gripper(target, speed=speed)
            record['jaw_commands'].append(dict(target=target,speed=speed,response=response));save()
            if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
                raise TransferError(('Pickup' if pickup else 'Release')+' uncertain; no lift or retry.')
            for _ in range(3):
                time.sleep(.25)
                state = healthy()
                near(state['pose_mm'], fresh['route'][0], .05)
                record['samples'].append(dict(phase=fresh['operation'],target=target,robot=state))
                if abs(e1(state) - target) > .15:
                    raise TransferError(('Pickup' if pickup else 'Release')+' did not settle; no lift.')
        baseline = e1(state)
        record['jaw_feedback_verified'] = True
        record['release_verified'] = not pickup
        save()
        from trajectory_queue import LuaTrajectory
        for index, (start, target, speed) in enumerate(zip(fresh['route'], fresh['route'][1:], SPEEDS)):
            state = healthy(baseline)
            near(state['pose_mm'], start, .05)
            def progress(stage, done, total):
                current = healthy(baseline)
                record['samples'].append(dict(leg=index+1, stage=stage, robot=current))
                run.say(f'Hamilton {"loaded" if pickup else "empty"} return: leg {index+1}/4, {stage} {done:.1f}/{total}')
            result = LuaTrajectory(service).execute(run, start, state['joints'], [target], cfg, speed,
                progress, reviewed=True, home_speed137=True, hamilton_release=True)
            if result.get('ok') is not True:
                raise TransferError('Hamilton return movement uncertain.')
            state = healthy(baseline)
            near(state['pose_mm'], target, .1)
            record['steps'].append(dict(target=target, speed=speed, result=result, after=state))
            save()
        record['status'] = ('pickup_and_loaded_home_completed_pending_operator_assessment' if pickup else 'release_and_empty_home_completed_pending_operator_assessment')
        return dict(ok=True,empty_home=not pickup,loaded_home=pickup,e1_mm=baseline,release_e1_mm=baseline if not pickup else None,operation=fresh['operation'],record=str(output))
    except Exception as error:
        record.update(status='failed_or_uncertain', error=str(error))
        record['stop_response'] = service.program('stop')
        raise
    finally:
        record.update(finished_at=time.time(), final_robot=service.status())
        save()
