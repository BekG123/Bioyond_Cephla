"""Read-only capture of revised alignment and a requested 30 mm descent."""
import hashlib
import json
import math
from pathlib import Path
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_alignment_plan import home_reference
from short_side_alignment_trial import FOLDER
from autonomy import check_path

root=Path(__file__).resolve().parents[1]
evidence=FOLDER/'corrected_alignment_02.json'
profile=root/'Pick and Hold/Descend/short_side_taught_endpoint.json'
if evidence.exists() or profile.exists():raise RuntimeError('Correction already captured; preserve it before another teaching')
s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok']
samples=[]
for _ in range(3):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    if s['sequence']['active'] or not r.get('ok') or not r.get('connected') or r.get('errors') or any(n[k] for k in ('moving','error','emergency','drag')):raise RuntimeError('Capture requires stationary healthy feedback')
    if n.get('external_units',{}).get('E2')!='degrees':raise RuntimeError('Holder angle feedback unavailable')
    if samples:
        near(r['pose_mm'],samples[0]['robot']['pose_mm'],.05)
        if abs(n['external_axes']['E2']-samples[0]['native']['external_axes']['E2'])>.05:raise RuntimeError('Holder moved during capture')
    samples.append(dict(at=time.time(),robot=r,native=n));time.sleep(.2)
keys=('X','Y','Z','Rz')
alignment={k:r['pose_mm'][k] for k in keys}
endpoint=dict(alignment,Z=alignment['Z']-30)
cfg=api('robot_params');assert s['envelope']['enabled']
env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in keys[:3]}
home,q,home_sha=home_reference()
points=[{k:math.floor(p[k]*100+.5)/100 for k in keys} for p in (alignment,endpoint)]
previous=home;offset=q['J1']-home['Z'];dense=[]
for leg,end in enumerate(points):
    origin=previous
    count=max(1,math.ceil(math.dist([origin[k] for k in keys[:3]],[end[k] for k in keys[:3]])),math.ceil(abs(end['Rz']-origin['Rz'])/.5))
    for i in range(1,count+1):
        p={k:origin[k]+(end[k]-origin[k])*i/count for k in keys}
        q=check_path(previous,p,q,cfg,env);q['J1']=p['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise RuntimeError('Joint travel exceeded')
        dense.append(dict(leg=leg,pose=p,joints=dict(q)));previous=p
    if leg==0:
        for key in ('J1','J2','J3','J4'):
            if abs(q[key]-r['joints'][key])>.5:raise RuntimeError('IK does not match taught winding')
prior=json.loads((FOLDER/'taught_alignment.json').read_bytes())
record=dict(status='operator_taught_correction_saved',at=time.time(),samples=samples,
    alignment=alignment,descent_endpoint=endpoint,holder_e2_degrees=n['external_axes']['E2'],
    change_from_original={k:alignment[k]-prior['target'][k] for k in keys},
    config=cfg,envelope=s['envelope'],home_source_sha256=home_sha,
    transmitted_candidate=points,ik_valid=True,dense_validation=dense,
    requested_speed=137,descent_drop_mm=30,gripper_open_e1_mm=28,
    physical_trial_performed=False,descent_at_speed137_verified=False,
    operator_instruction='Save this new correction coordinate as ideal + descent of 30 mm at speed 137.',
    prior_grip_fault_preserved=True)
with evidence.open('x') as f:json.dump(record,f,indent=2,allow_nan=False)
settings=dict(schema=1,status='taught_ideal_pending_corrected_route_trial',
    alignment=alignment,endpoint=endpoint,descent_drop_mm=30,
    approach_speed=137,descent_speed=137,gripper_open_e1_mm=28,
    holder_e2_degrees=n['external_axes']['E2'],grip_target_e1_mm=None,
    execution_pattern='One coordinated approach MoveL, followed by one vertical descent MoveL; no intermediate approach stops.',
    evidence=str(evidence.relative_to(root)).replace('\\','/'),evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
    ik_valid=True,corrected_route_physically_tested=False,descent_speed137_physically_tested=False,
    automatic_execution_enabled=False)
with profile.open('x') as f:json.dump(settings,f,indent=2,allow_nan=False)
print(json.dumps(settings,indent=2))
