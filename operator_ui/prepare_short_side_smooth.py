"""Offline review of a single MoveL replacing ten near-collinear commands."""
import hashlib
import json
import math
import time
from short_side_alignment_trial import reference, candidate_points, validate_route, FOLDER, PLAN_SHA
from trajectory_queue import checksum, prepare_points
from autonomy import check_path

plan,taught=reference()
start=plan['home'];points=candidate_points(plan,'smooth_direct');end=points[0]
env={k:(taught['envelope'][k]['min'],taught['envelope'][k]['max']) for k in ('X','Y','Z')}
validate_route(start,points,plan['home_joints'],taught['config'],env,'smooth_direct')
transmitted,_=prepare_points(start,plan['home_joints'],points,taught['config'],reviewed=True,short_side_alignment='smooth_direct')
q=dict(plan['home_joints']);previous=start;samples=[]
for i in range(1,401):
    p={k:start[k]+(end[k]-start[k])*i/400 for k in start}
    q=check_path(previous,p,q,taught['config'],env)
    q['J1']=p['Z']+plan['home_joints']['J1']-start['Z']
    assert 0<=q['J1']<=400 and abs(q['J3'])<=180
    samples.append(dict(pose=p,joints=dict(q)));previous=p
# Parameter-matched error bounds every former segment; linear interpolation makes
# the largest error occur at a vertex. This is not a collision-mesh assessment.
errors=[]
for i,p in enumerate(plan['candidates']['direct']['points'],1):
    linear={k:start[k]+(end[k]-start[k])*i/10 for k in start}
    errors.append(dict(xyz_mm=math.dist([p[k] for k in ('X','Y','Z')],[linear[k] for k in ('X','Y','Z')]),yaw_deg=abs(p['Rz']-linear['Rz'])))
record=dict(status='offline_validated_not_yet_run',created_at=time.time(),parent_sha256=PLAN_SHA,
    baseline_trial_sha256=hashlib.sha256((FOLDER/'trial_direct.json').read_bytes()).hexdigest(),
    operator_feedback='Jaws correctly open and aligned; remove separate turns and retry a continuous approach.',
    candidate='smooth_direct',start=start,points=transmitted,checksum=checksum(transmitted),
    speed=137,queues=1,move_l_commands=1,completion_barriers=1,e1=28,e2=taught['e2_degrees'],
    max_difference_mm=max(e['xyz_mm'] for e in errors),max_difference_deg=max(e['yaw_deg'] for e in errors),
    clearance='Operator cleared the same path and open-jaw sweep and observed the ten-command baseline; no mesh collision validation.',
    samples=samples,source_hashes={name:hashlib.sha256((FOLDER.parents[2]/name).read_bytes()).hexdigest() for name in ('short_side_alignment_trial.py','trajectory_queue.py')})
with (FOLDER/'smooth_plan.json').open('x') as f:json.dump(record,f,indent=2)
print(json.dumps({k:v for k,v in record.items() if k!='samples'},indent=2))
