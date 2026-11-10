"""Offline bidirectional IK through the operator's clearance waypoint."""
import hashlib
import json
import math
import time
from hamilton_short_side_trial import FOLDER,reference,PLAN_SHA
from plan_short_side_hamilton import validate
from trajectory_queue import checksum

KEYS=('X','Y','Z','Rz')
def quantize(p):return {k:math.floor(p[k]*100+.5)/100 for k in KEYS}

def build():
    p,parent=reference();raw=(FOLDER/'taught_hamilton_short_side_turning01.json').read_bytes();taught=json.loads(raw)
    if taught['parent_plan_sha256']!=PLAN_SHA or taught['config']!=p['config'] or taught['envelope']!=p['global_envelope']:
        raise ValueError('Teaching and parent configuration differ')
    home=quantize(parent['home']);site=quantize(parent['taught_endpoint']);turn=quantize(taught['target'])
    cfg=p['config'];env={k:tuple(v) for k,v in p['station_envelope'].items()}
    definitions={
        'forward':(home,[turn,site],parent['home_joints'],parent['measured_endpoint_joints']),
        'reverse':(site,[turn,home],parent['measured_endpoint_joints'],parent['home_joints'])}
    routes={}
    for direction,(start,points,q,expected) in definitions.items():
        # Validate the turning pose's actual taught joint branch separately.
        first=validate(start,[turn],q,cfg,env,taught['joints'])
        result=validate(start,points,q,cfg,env,expected)
        if not first['workspace_valid'] or not result['workspace_valid']:raise ValueError('Workspace violation')
        routes[direction]=dict(start=start,start_joints=q,points=points,validation=result,
            turning_pose_validation=first,speed=137,queues=1,move_l_commands=2,completion_barriers=1,
            payload=dict(header=[2,137,-1]+[start[k] for k in KEYS]+[q[k] for k in ('J1','J2','J3','J4')],
                         points=points,checksum=checksum(points)),
            external_axes='Preserve current E1/E2; no grip or holder commands')
    stopped=json.loads((FOLDER/'hamilton_short_side_trial01_stopped.json').read_bytes())
    stop=stopped['state']['robot']['pose_mm']
    return dict(status='offline_ik_valid_pending_clearance_trial',created_at=time.time(),
        parent_plan_sha256=PLAN_SHA,taught_waypoint_sha256=hashlib.sha256(raw).hexdigest(),
        home_source_sha256=parent['home_sha256'],endpoint_source_sha256=parent['taught_sha256'],
        operator_intent='Use the manually taught turning coordinate to avoid the Hamilton collision; preserve site-4 and Home endpoints.',
        taught_turning_pose=taught['target'],quantized_turning_pose=turn,
        displacement_from_collision_stop={k:taught['target'][k]-stop[k] for k in KEYS},
        config=cfg,global_envelope=p['global_envelope'],station_envelope=env,
        global_limits_changed=False,routes=routes,
        failed_direct_route_retained=True,failed_direct_route_selected=False,
        exact_turning_pose_required=True,regrouping_allowed=False,
        hardware_tested=False,execution_enabled=False,collision_clearance_verified=False,
        limitation='IK checks reach, continuous joint branch and configured limits. No calibrated Hamilton collision mesh exists in this check. The taught waypoint is not proof of clearance along either connecting segment.',
        controller_faults_at_teaching=taught['samples'][-1]['robot']['errors'],
        no_fault_reset_or_robot_motion=True)

def main():
    path=FOLDER/'hamilton_short_side_via_turning01_plan.json'
    if path.exists():raise RuntimeError('Revision already saved; preserve before replanning')
    p=build()
    with path.open('x') as f:json.dump(p,f,indent=2)
    print(json.dumps(dict(path=str(path),turning_pose=p['quantized_turning_pose'],
        routes={k:dict(points=v['points'],distance_mm=v['validation']['length_mm'],joint_ranges=v['validation']['joint_ranges'],
                       turning_joint_error=v['turning_pose_validation']['endpoint_joint_error']) for k,v in p['routes'].items()},
        speed=137,hardware_tested=False),indent=2))

if __name__=='__main__':main()
