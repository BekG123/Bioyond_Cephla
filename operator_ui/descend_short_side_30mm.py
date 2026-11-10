"""One authorized 30 mm open-jaw descent from the accepted alignment."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
from proof_lift_plate import api, near
from draggo import DragGoRPC
from short_side_alignment_trial import FOLDER, reference
from autonomy import check_path

plan,taught=reference()
trial=FOLDER/'trial_smooth_direct.json'
accepted=json.loads(trial.read_text())
assert accepted['status']=='completed_awaiting_operator_inspection'
acceptance=FOLDER/'smooth_operator_acceptance.json'
if not acceptance.exists():
    with acceptance.open('x') as f:
        json.dump(dict(status='operator_accepted',at=time.time(),feedback='Yes, that was perfect. Save this.',
            trial_sha256=hashlib.sha256(trial.read_bytes()).hexdigest(),
            candidate_sha256=hashlib.sha256((FOLDER/'smooth_plan.json').read_bytes()).hexdigest(),
            endpoint=accepted['final_robot']['pose_mm'],speed=137,e1=28,
            scope='Home to turned-holder alignment; no grip height or jaw closure accepted yet'),f,indent=2)

path=FOLDER/'descent_30mm_trial.json'
if path.exists():raise RuntimeError('Descent already attempted; inspect the existing receipt before retrying')
start=accepted['final_robot']['pose_mm']
# Use the accepted quantized alignment Z, not sub-resolution feedback rounding.
start=dict(start,Z=accepted['queue_result']['endpoint']['Z'])
target={k:start[k] for k in ('X','Y','Z','Rz')};target['Z']-=30
record=dict(status='prepared',started_at=time.time(),start=start,target=target,speed=5,samples=[],
    authorization='Operator accepted alignment and requested about 3 cm downward, then stop for further instructions.',
    grip_commands=[],parent_sha256=hashlib.sha256(trial.read_bytes()).hexdigest())
def save():path.write_text(json.dumps(record,indent=2))
def check():
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    if not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled') or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running' or not r.get('lua_app_initialized'):
        raise RuntimeError('Healthy running Auto required; no reset or startup allowed')
    if s['sequence']['active'] or any(n[k] for k in ('manual','drag','error','emergency')):
        raise RuntimeError('Conflicting activity or controller fault')
    if abs(n['external_axes']['E1']-28)>.15 or abs(n['external_axes']['E2']-taught['e2_degrees'])>.1:
        raise RuntimeError('Jaw opening or taught holder orientation changed')
    p=r['pose_mm']
    for k in ('X','Y','Rz'):
        if abs(p[k]-start[k])>.2:raise RuntimeError('Descent left vertical path')
    if not target['Z']-.2<=p['Z']<=start['Z']+.2:raise RuntimeError('Descent exceeded vertical bounds')
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    return s,n

s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok']
s,n=check();near(s['robot']['pose_mm'],start,.1)
assert not n['moving'] and api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
assert s['envelope']['enabled']
env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
cfg=api('robot_params');check_path(start,target,s['robot']['joints'],cfg,env)
assert 0<=s['robot']['joints']['J1']-30<=400
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
            time.sleep(.15)
        response=future.result();record['response']=response
    if not response.get('ok') or response.get('recovered'):raise RuntimeError('Descent completion uncertain')
    s,n=check();near(s['robot']['pose_mm'],target,.1)
    if n['moving']:raise RuntimeError('Arm still moving after command returned')
    record.update(status='completed_awaiting_height_inspection',final_state=s)
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error))
    if 'stop_response' not in record:
        try:record['stop_response']=api('program',{'action':'stop'})
        except Exception as stop_error:record['stop_error']=str(stop_error)
    raise
finally:
    record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],e1=n['external_axes']['E1'],report=str(path))))
