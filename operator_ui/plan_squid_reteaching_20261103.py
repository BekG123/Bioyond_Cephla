"""GET-only capture of the new Squid teaching and offline Home route checks."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import time

from capture_squid_approach_20261103 import FOLDER, KEYS, save, sha
from prepare_squid_destination import get, validate
from projected_pickup import ROOT, PROFILE
from scope_step_trial import near

PARENT = FOLDER/'approach_20261103T180838653466Z.json'
PARENT_SHA = 'a2fb701e3224515e4c4437332b24f4be360aa1c62e074cc19eb39ff6bd4ae613'
HOME_RUN = FOLDER/'loaded_trial_e38de102763544dc9b872eaabe9bcb69.json'


def main():
    first = get('state')
    time.sleep(.3)
    state = get('state')
    for s in (first, state):
        r = s['robot']
        if not r.get('connected') or not r.get('ok') or r.get('errors') or s['sequence']['active']:
            raise RuntimeError('Connected, healthy, stationary controller required')
    r = state['robot']
    near(first['robot']['pose_mm'], r['pose_mm'], .05)
    if any(abs(first['robot']['joints'][k]-r['joints'][k])>.05 for k in r['joints']):
        raise RuntimeError('Joints moved during capture')
    target = {k:r['pose_mm'][k] for k in KEYS}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    capture = FOLDER/('taught_'+stamp+'.json')
    save(capture, dict(target=target, source_state=state, preceding_state=first,
        operator_intent='Current manually positioned pose is ideal Squid destination; plan from saved Home.',
        payload_state='Manually changed; not verified for execution', hardware_motion_commands_sent=False))
    print(json.dumps(dict(capture=str(capture), target=target)), flush=True)
    if sha(PARENT)!=PARENT_SHA:
        raise RuntimeError('Parent changed; capture retained')
    parent=json.loads(PARENT.read_bytes())
    evidence=json.loads(HOME_RUN.read_bytes())
    if evidence['candidate_sha256']!=PARENT_SHA or evidence['status']!='loaded_above_squid_awaiting_operator_teaching':
        raise RuntimeError('Completed Home-to-overhead evidence required')
    home_robot=evidence['source_state']['robot']
    if home_robot['errors'] or evidence['source_state']['sequence']['state']!='done':
        raise RuntimeError('Home evidence not healthy and completed')
    cfg=get('robot_params')
    env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in KEYS[:3]}
    if not state['envelope']['enabled'] or cfg!=parent['cfg'] or env!=parent['envelope']:
        raise RuntimeError('Settings changed')
    points_path=ROOT/'operator_ui/points.json'
    points=json.loads(points_path.read_text(encoding='utf-8-sig'))
    saved=points['points'][points['roles']['home']]
    home={k:home_robot['pose_mm'][k] for k in KEYS}
    near(home,dict(X=saved['x'],Y=saved['y'],Z=saved['z_grip'],Rz=saved['rz']),.01)
    route=deepcopy(parent['routes']['forward'])
    near(home,route[0],.01)
    route[0]=home
    if target['Z']+5>route[-2]['Z']:
        raise RuntimeError('New endpoint needs higher clearance; capture retained')
    route[-2]=dict(target,Z=route[-2]['Z'])
    route[-1]=target
    checks={}
    for name,path in [('forward',route),('approach',route[:-1])]:
        checks[name]=validate(path,home_robot['joints'],cfg,env)
        rounded=[{k:math.floor(v*100+.5)/100 for k,v in p.items()} for p in path]
        checks['quantized_'+name]=validate(rounded,home_robot['joints'],cfg,env)
    difference={k:checks['forward']['final_joints'][k]-r['joints'][k] for k in r['joints']}
    if any(abs(v)>.5 for v in difference.values()):
        raise RuntimeError('Arrival joint winding differs from teaching')
    candidate=dict(status='offline_checked_pending_supervised_trial',capture=str(capture),capture_sha256=sha(capture),
        parent=str(PARENT),parent_sha256=PARENT_SHA,home_evidence=str(HOME_RUN),home_evidence_sha256=sha(HOME_RUN),
        saved_points_sha256=sha(points_path),pickup_profile_sha256=sha(PROFILE),source_state=state,cfg=cfg,envelope=env,
        routes=dict(forward=route,approach_only=route[:-1]),target=target,stop_before_descent=route[-2],
        validation=checks,taught_joint_difference=difference,
        delta_from_parent={k:target[k]-parent['routes']['forward'][-1][k] for k in KEYS},
        planned_leg_speeds=[137,137,137,5],payload_state='Unverified after manual changes',
        hardware_motion_commands_sent=False,deployed=False,execution_authorized=False,
        holder_descent_authorized=False,release_authorized=False,collision_clearance_verified=False,
        limitations='Dense IK and workspace checks do not model holder, plate or microscope collision volumes. Prior lower descent fault is preserved; this new destination is untested.')
    output=FOLDER/('destination_reteach_'+stamp+'.json')
    save(output,candidate)
    print(json.dumps(dict(candidate=str(output),sha256=sha(output),route=route,
        speeds=candidate['planned_leg_speeds'],samples=checks['forward']['sample_count'],
        joint_difference=difference,delta=candidate['delta_from_parent'])),flush=True)


if __name__=='__main__':
    main()
