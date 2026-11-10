"""Record accepted placement and check its return offline. No motion."""
import hashlib
import json
import time
from short_side_full_trial import reference, receipt
from researcher_home import queued_station_stages
from autonomy import check_path

p,parent,grip=reference('04');departure=p['routes']['departure']
home=parent['home'];turn=departure['points'][-1]
q=departure['validation']['endpoint_joints']
env={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
stages=queued_station_stages(turn,home,q,p['config'],env)
previous=turn;checked=[];offset=q['J1']-turn['Z']
for stage in stages:
    points=stage['points'] if stage['kind']=='queue' else [dict(previous,Rz=stage['rz'])]
    for point in points:
        q=check_path(previous,point,q,p['config'],env);q['J1']=point['Z']+offset
        assert 0<=q['J1']<=400 and abs(q['J3'])<=180
        checked.append(dict(pose=point,joints=dict(q)));previous=point
raw=receipt('hamilton','04').read_bytes()
assert json.loads(raw)['status']=='completed'
accepted=dict(at=time.time(),accepted=True,hamilton_sha256=hashlib.sha256(raw).hexdigest(),
    operator_quote='Awesome, it worked. Now, take it back home and if that works, save it as a succesful Hamilton path',
    observation='Operator accepted corrected arrival; return pending its own trial and payload inspection.')
with receipt('operator_acceptance','04').open('x') as stream:json.dump(accepted,stream,indent=2)
record=dict(at=time.time(),departure=departure,home=home,home_stages=stages,home_checked=checked,
    grip_preserved_mm=25,translation_speed=137,home_wrist_speed=30,
    no_program_restart=True,gripper_commands=[],execution_enabled=False,
    authorization='User requested loaded Home return after accepting placement; existing taught turn and Home procedure retained.',
    physical_return_verified=False)
with receipt('return_plan','04').open('x') as stream:json.dump(record,stream,indent=2)
print(json.dumps(dict(departure=departure['points'],speeds=departure['segment_speeds'],home_stages=stages,ik_valid=True),indent=2))
