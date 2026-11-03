"""Record operator-taught Z266.81; GET-only capture and offline checks."""
from copy import deepcopy
import json
import time
from capture_squid_approach_20261103 import FOLDER, sha, save
from prepare_squid_destination import get, validate

PARENT=FOLDER/'destination_reteach_20261103T185217893840Z.json'
OUTPUT=FOLDER/'destination_final_z266p81_20261103.json'


def main():
    if OUTPUT.exists():raise RuntimeError('Final-height record already exists')
    if sha(PARENT)!='7846a622f2cd4ebdc2ea0d518b95a06d9c184cb156c001dacf5f49b5b78b2a02':
        raise RuntimeError('Parent changed')
    first=get('state');time.sleep(.3);state=get('state')
    for s in (first,state):
        r=s['robot']
        if not r.get('connected') or not r.get('ok') or r.get('errors') or s['sequence']['active']:
            raise RuntimeError('Healthy stationary capture required')
    r=state['robot']
    if any(abs(first['robot']['pose_mm'][k]-r['pose_mm'][k])>.05 for k in ('X','Y','Z','Rz')):
        raise RuntimeError('Pose moved during capture')
    if abs(r['pose_mm']['Z']-266.81)>.05:raise RuntimeError('Live height differs from instruction')
    parent=json.loads(PARENT.read_bytes());cfg=get('robot_params')
    env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
    if not state['envelope']['enabled'] or cfg!=parent['cfg'] or env!=parent['envelope']:
        raise RuntimeError('Settings changed')
    home_path=__import__('pathlib').Path(parent['home_evidence'])
    if sha(home_path)!=parent['home_evidence_sha256']:raise RuntimeError('Home evidence changed')
    initial=json.loads(home_path.read_bytes())['source_state']['robot']['joints']
    route=deepcopy(parent['routes']['forward']);route[-1]['Z']=266.81
    checked=validate(route,initial,cfg,env)
    rounded=[{k:round(v,2) for k,v in pt.items()} for pt in route]
    quantized=validate(rounded,initial,cfg,env)
    result=deepcopy(parent)
    result.update(status='operator_taught_final_height_offline_checked_pending_replay',
        parent=str(PARENT),parent_sha256=sha(PARENT),captured_at=time.time(),source_state=state,
        preceding_state=first,target=route[-1],routes=dict(forward=route,approach_only=route[:-1]),
        validation=dict(forward=checked,quantized_forward=quantized),
        operator_instruction='Ignore grip; record final descent height after manual lowering: Z266.81 mm.',
        height_only_change=True,measured_pose=r['pose_mm'],final_height_mm=266.81,
        descent_distance_mm=route[-2]['Z']-266.81,
        delta_from_parent={k:route[-1][k]-parent['target'][k] for k in route[-1]},
        payload_state='Manual changes; current grip is not a release or payload acceptance.',
        hardware_motion_commands_sent=False,deployed=False,execution_authorized=False,
        holder_descent_authorized=False,release_authorized=False,collision_clearance_verified=False,
        limitations='User accepted final height. Saved XY/yaw preserved; minor live manual offsets are recorded separately. Automated descent to the new height has not been tested.')
    result.pop('capture',None);result.pop('capture_sha256',None);result.pop('taught_joint_difference',None)
    save(OUTPUT,result)
    print(json.dumps(dict(path=str(OUTPUT),sha256=sha(OUTPUT),target=result['target'],
        descent_mm=result['descent_distance_mm'],samples=checked['sample_count'])),flush=True)


if __name__=='__main__':main()
