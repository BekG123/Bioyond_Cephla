"""Offline IK candidates for taught site 4; no motion, no limit changes."""
import hashlib
import json
import math
import time
from short_side_alignment_trial import FOLDER
from short_side_alignment_plan import home_reference
from autonomy import check_path
from trajectory_queue import checksum

KEYS=('X','Y','Z','Rz')

def validate(start,points,joints,cfg,envelope,expected):
    q=dict(joints);previous=start;offset=q['J1']-start['Z'];samples=[];length=0
    ranges={k:[q[k],q[k]] for k in ('J1','J2','J3','J4')}
    violations=[]
    for index,end in enumerate(points):
        origin=previous
        distance=math.dist([origin[k] for k in KEYS[:3]],[end[k] for k in KEYS[:3]])
        count=max(1,math.ceil(distance),math.ceil(abs(end['Rz']-origin['Rz'])/.25))
        for i in range(count+1):
            p={k:origin[k]+(end[k]-origin[k])*i/count for k in KEYS}
            # Separate pure kinematic feasibility from the live workspace gate.
            # Passing None here is analysis only; this module has no robot client.
            q=check_path(previous,p,q,cfg,None);q['J1']=p['Z']+offset
            if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise ValueError('Joint travel exceeded')
            for k in ranges:ranges[k]=[min(ranges[k][0],q[k]),max(ranges[k][1],q[k])]
            outside={k:p[k] for k,(lo,hi) in envelope.items() if not lo<=p[k]<=hi}
            if outside:violations.append(dict(segment=index,pose=p,outside=outside))
            samples.append(dict(segment=index,pose=p,joints=dict(q)));previous=p
        length+=distance
    errors={k:q[k]-expected[k] for k in ('J1','J2','J3','J4')}
    if max(abs(v) for v in errors.values())>.5:raise ValueError('Endpoint does not match taught joint winding')
    return dict(ik_and_joint_limits_valid=True,joint_ranges=ranges,endpoint_joints=q,
        endpoint_joint_error=errors,dense_samples=samples,length_mm=length,
        workspace_valid=not violations,workspace_violations=violations,
        collision_clearance_verified=False)

def main():
    raw=(FOLDER/'taught_hamilton_site4_short_side.json').read_bytes();taught=json.loads(raw)
    home,hq,home_sha=home_reference();target=taught['target'];cfg=taught['config']
    env={k:(taught['envelope'][k]['min'],taught['envelope'][k]['max']) for k in KEYS[:3]}
    quantize=lambda p:{k:math.floor(p[k]*100+.5)/100 for k in KEYS}
    end=quantize(target)
    candidates={}
    for name,points in [('direct',[end]),('level_then_vertical',[dict(end,Z=home['Z']),end])]:
        try:
            result=validate(home,points,hq,cfg,env,taught['joints'])
            candidates[name]=dict(points=points,speed=137,queues=1,move_l_commands=len(points),zone=-1,
                checksum=checksum(points),validation=result)
        except ValueError as e:candidates[name]=dict(ik_and_joint_limits_valid=False,error=str(e))
    direct=candidates['direct']
    if 'validation' not in direct:raise ValueError('Direct candidate has no valid IK solution')
    reverse=validate(end,[home],taught['joints'],cfg,env,hq)
    forward_payload=dict(header=[1,137,-1]+[home[k] for k in KEYS]+[hq[k] for k in ('J1','J2','J3','J4')],
        points=[end],checksum=checksum([end]),completion_barriers=1,
        external_axes='Preserve measured axes; no E1/E2 commands. Refresh pose and joints before any live upload.')
    path=FOLDER/'hamilton_short_side_ik_plan.json'
    if path.exists():raise ValueError('Plan exists; preserve before revising')
    record=dict(status='offline_ik_candidate_requires_clearance_and_station_route_review',at=time.time(),
        taught_endpoint=target,home=home,home_joints=hq,measured_endpoint_joints=taught['joints'],
        taught_sha256=hashlib.sha256(raw).hexdigest(),home_sha256=home_sha,
        config=cfg,envelope=taught['envelope'],candidates=candidates,
        selected_candidate='direct',selection_reason='Shortest Cartesian path between these endpoints, one coordinated XYZ/yaw MoveL; not proof of obstacle clearance.',
        reverse=dict(start=end,points=[home],speed=137,queues=1,move_l_commands=1,validation=reverse),
        lua_queue_candidate=forward_payload,
        global_limits_changed=False,existing_hamilton_path_replaced=False,execution_enabled=False,
        blockers=['New diagonal loaded arm/claw/plate sweep has not been physically reviewed.',
            'Taught endpoint Z52.027 is below global travel floor Z70. Needs exact reviewed station approach; no global envelope expansion applied.'],
        grip_reference='Pick and Hold/Grip/short_side_48well_reference.json',
        captured_e1_mm=taught['external_axes']['E1'],grasp_state_requires_live_verification=True,
        live_test_performed=False)
    with path.open('x') as f:json.dump(record,f,indent=2,allow_nan=False)
    summary=dict(path=str(path),endpoint=target,points=direct['points'],speed=137,
        distance_mm=direct['validation']['length_mm'],joints=direct['validation']['endpoint_joints'],
        joint_ranges=direct['validation']['joint_ranges'],workspace_valid=direct['validation']['workspace_valid'],
        reverse_ik_valid=reverse['ik_and_joint_limits_valid'],alternative_length_mm=candidates['level_then_vertical']['validation']['length_mm'])
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
