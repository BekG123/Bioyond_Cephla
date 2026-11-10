"""One authorized 5 mm proof lift, preserving the inspected 26 mm closure."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_alignment_trial import FOLDER,reference_for_candidate
from autonomy import check_path

_,taught=reference_for_candidate('corrected02')
parent=FOLDER/'grip_corrected02_28_to_26_trial.json'
grip=json.loads(parent.read_bytes())
assert grip['status']=='stopped_at_26_awaiting_gap_inspection'
pose=grip['final_state']['robot']['pose_mm']
target={k:pose[k] for k in ('X','Y','Z','Rz')};target['Z']+=5
path=FOLDER/'proof_lift_corrected02_e1_26.json'
if path.exists():raise RuntimeError('Proof lift already attempted; inspect before retrying')
record=dict(status='prepared',at=time.time(),start=pose,target=target,speed=5,e1_target=26,
    grip_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),samples=[],
    operator_contact_observation='Touching evenly, no gap.',
    authorization='Operator requested a small lift after confirming even contact.',
    gripper_commands=[],secure_grasp_verified=False)
def save():path.write_text(json.dumps(record,indent=2))
def check():
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    if not r.get('ok') or not r.get('connected') or not r.get('enabled') or r.get('errors') or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running' or not r.get('lua_app_initialized'):raise RuntimeError('Healthy running Auto required; no preparation with held plate')
    if s['sequence']['active'] or any(n[k] for k in ('manual','drag','error','emergency')):raise RuntimeError('Conflicting activity or controller fault')
    if abs(n['external_axes']['E1']-26)>.07 or abs(n['external_axes']['E2']-taught['e2_degrees'])>.1:raise RuntimeError('Grip or holder angle changed')
    p=r['pose_mm']
    if any(abs(p[k]-pose[k])>.15 for k in ('X','Y','Rz')) or not pose['Z']-.15<=p['Z']<=target['Z']+.15:raise RuntimeError('Lift left its vertical corridor')
    return s,n
s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok']
s,n=check();near(s['robot']['pose_mm'],pose,.1)
assert not n['moving'] and api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
assert s['envelope']['enabled']
env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
check_path(pose,target,s['robot']['joints'],api('robot_params'),env)
assert 0<=s['robot']['joints']['J1']+5<=400
command=dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=5,interpolation='linear')
record.update(command=command,status='attempt_started')
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(api,'move',command)
        while not future.done():
            try:check();save()
            except Exception:
                record['stop_response']=api('program',{'action':'stop'});raise
            time.sleep(.1)
        record['response']=future.result();save()
    if not record['response'].get('ok') or record['response'].get('recovered'):raise RuntimeError('Lift completion uncertain; no retry')
    for _ in range(5):
        s,n=check();near(s['robot']['pose_mm'],target,.1);time.sleep(.2)
    if n['moving']:raise RuntimeError('Arm still moving')
    record.update(status='lift_completed_awaiting_retention_inspection',final_state=s)
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error))
    if 'stop_response' not in record:
        try:record['stop_response']=api('program',{'action':'stop'})
        except Exception as e:record['stop_error']=str(e)
    raise
finally:record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],e1=n['external_axes']['E1'],report=str(path))))
