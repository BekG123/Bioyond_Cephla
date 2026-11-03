"""GET-only plan for a loaded reverse route; no gripper or motion commands."""
from copy import deepcopy
import json
import math
import time
from capture_squid_approach_20261103 import FOLDER, save, sha
from prepare_squid_destination import get, validate
from scope_step_trial import near

SOURCE=FOLDER/'destination_final_z266p81_20261103.json'
SOURCE_SHA='ac004fd846bf2333a29f29374b7091b7c042cb6cf31d53ca09c45432412a84b8'
OUTPUT=FOLDER/'loaded_return_final_z266p81_20261103.json'


def main():
    if OUTPUT.exists():raise RuntimeError('Plan already saved')
    if sha(SOURCE)!=SOURCE_SHA:raise RuntimeError('Destination changed')
    candidate=json.loads(SOURCE.read_bytes())
    first=get('state');time.sleep(.3);state=get('state');robot=state['robot']
    for s in (first,state):
        r=s['robot']
        if not r.get('connected') or not r.get('ok') or r.get('errors') or s['sequence']['active']:
            raise RuntimeError('Healthy stationary feedback required')
    near(first['robot']['pose_mm'],robot['pose_mm'],.05)
    forward=candidate['routes']['forward'];seat=forward[-1]
    near(robot['pose_mm'],seat,.1)
    cfg=get('robot_params')
    env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
    if not state['envelope']['enabled'] or cfg!=candidate['cfg'] or env!=candidate['envelope']:
        raise RuntimeError('Settings changed')
    # Same local lift and reverse ordering as run_accepted_squid_roundtrip.py.
    nominal=[seat,dict(seat,Z=seat['Z']+5),*reversed(forward[:-1])]
    start={k:robot['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    live=[start,dict(start,Z=start['Z']+5),dict(start,Z=forward[-2]['Z']),*deepcopy(list(reversed(forward[:-2])))]
    checks={}
    for name,path in [('nominal',nominal),('from_capture',live)]:
        checked=validate(path,robot['joints'],cfg,env)
        rounded=[{k:math.floor(v*100+.5)/100 for k,v in point.items()} for point in path]
        checked['quantized_final_joints']=validate(rounded,robot['joints'],cfg,env)['final_joints']
        checks[name]=checked
    from pathlib import Path
    home_evidence=Path(candidate['home_evidence'])
    if sha(home_evidence)!=candidate['home_evidence_sha256']:raise RuntimeError('Home evidence changed')
    expected=json.loads(home_evidence.read_bytes())['source_state']['robot']['joints']
    delta={k:checks['from_capture']['final_joints'][k]-expected[k] for k in expected}
    if any(abs(v)>.5 for v in delta.values()):raise RuntimeError('Home joint winding mismatch')
    record=dict(status='offline_checked_loaded_return_pending_supervised_trial',source=str(SOURCE),source_sha256=SOURCE_SHA,
        captured_at=time.time(),source_state=state,preceding_state=first,cfg=cfg,envelope=env,
        routes=dict(nominal=nominal,from_capture=live),validation=checks,home_joint_difference=delta,
        leg_speeds=[5,5,137,137,137],lift_mm=5,preserve_gripper=True,gripper_commands=[],
        operator_intent='Calculate reverse route Home with the plate retained; do not open claws.',
        payload='Plate held, per operator; no new physical retention observation claimed.',
        captured_e1_mm=robot['external_axes']['E1'],
        execution_authorized=False,hardware_motion_commands_sent=False,collision_clearance_verified=False,
        execution_requirements=['Recheck current pose, joints, payload and clear lift route.',
            'Already-running Auto required by existing loaded executor; never restart the program with a held plate.',
            'No opening, regrip, fault reset or automatic retry. Stop on fault or changed grip feedback.'],
        limitations='Current controller is Manual/Paused. Kinematic checks do not certify holder or plate clearance. Loaded reverse path at the new final height has not been physically tested.')
    save(OUTPUT,record)
    print(json.dumps(dict(path=str(OUTPUT),sha256=sha(OUTPUT),route=live,speeds=record['leg_speeds'],
        samples=checks['from_capture']['sample_count'],home_joint_difference=delta)),flush=True)


if __name__=='__main__':main()
