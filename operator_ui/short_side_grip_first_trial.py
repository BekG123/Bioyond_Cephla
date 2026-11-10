"""First bounded short-side closure: 28 -> 27 -> 26; no lift or retries."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import time
import sys
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_alignment_trial import FOLDER,reference,reference_for_candidate

corrected='--corrected02' in sys.argv
_,taught=reference_for_candidate('corrected02') if corrected else reference()
parent=FOLDER/('home_corrected02_descent_trial.json' if corrected else 'descent_30mm_trial.json')
descent=json.loads(parent.read_bytes())
assert descent['status']==('completed_awaiting_operator_inspection' if corrected else 'completed_awaiting_height_inspection')
pose=descent['final_state']['robot']['pose_mm']
path=FOLDER/('grip_corrected02_28_to_26_trial.json' if corrected else 'grip_28_to_26_trial.json')
if path.exists():raise RuntimeError('Trial already attempted; inspect receipt before further closure')
record=dict(status='prepared',at=time.time(),pose=pose,speed=5,targets=[27,26],steps=[],samples=[],
    authorization='Operator accepted 30 mm descent and requested supervised closure to determine short-side grip position.',
    descent_operator_accepted=True,descent_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
    baseline_plate_present=True,grasp_verified=False,force_limits_changed=False,arm_motion=False)
def save():path.write_text(json.dumps(record,indent=2))
def check(low=25.9,high=28.1):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    if not r.get('ok') or not r.get('connected') or not r.get('enabled') or r.get('errors') or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running' or not r.get('lua_app_initialized'):
        raise RuntimeError('Healthy already-running Auto required')
    if s['sequence']['active'] or any(n[k] for k in ('manual','drag','error','emergency')):raise RuntimeError('Conflicting activity or fault')
    near(r['pose_mm'],pose,.1)
    if abs(n['external_axes']['E2']-taught['e2_degrees'])>.1:raise RuntimeError('Holder angle changed')
    if not low<=n['external_axes']['E1']<=high:raise RuntimeError('Jaw position outside this closure step')
    return s,n
def torque():
    r=api('gripper',{'action':'torque'})
    if not r.get('ok') or not r.get('telemetry_live') or r.get('recovered'):raise RuntimeError('Fresh torque report unavailable')
    if not all(isinstance(r.get(k),(int,float)) and math.isfinite(r[k]) for k in ('e1_position','e1_torque')):raise RuntimeError('Invalid torque data')
    return r

s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok']
s,n=check(27.93,28.07)
assert not n['moving']
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
with path.open('x') as f:json.dump(record,f,indent=2)
sent=False
try:
    record['baseline']=[torque() for _ in range(3)];save()
    previous=28
    for target in record['targets']:
        check(previous-.07,previous+.07)
        item=dict(target_e1_mm=target,started_at=time.time());record['steps'].append(item);save()
        sent=True
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(api,'gripper',dict(action='move',e1=target,speed=5))
            while not future.done():
                try:check(target-.07,previous+.07);save()
                except Exception:
                    record['stop_response']=api('program',{'action':'stop'});raise
                time.sleep(.1)
            item['response']=future.result();save()
        r=item['response']
        if not r.get('ok') or r.get('recovered') or r.get('gripper_warning'):raise RuntimeError('Uncertain closing step; no retry')
        if r.get('gripper',{}).get('grip_detected'):raise RuntimeError('Controller contact indication; inspect before further closure')
        item['stationary_reports']=[]
        for _ in range(3):
            check(target-.07,target+.07)
            t=torque();item['stationary_reports'].append(t);save()
            if abs(t['e1_position']-target)>.07:raise RuntimeError('Jaw did not reach target; inspect contact')
            time.sleep(.15)
        previous=target
    for _ in range(5):check(25.93,26.07);time.sleep(.2)
    s,n=check(25.93,26.07)
    if n['moving']:raise RuntimeError('Gripper still moving')
    record.update(status='stopped_at_26_awaiting_gap_inspection',final_state=s)
except Exception as error:
    record.update(status='stopped_or_uncertain',error=str(error))
    if sent and 'stop_response' not in record:
        try:record['stop_response']=api('program',{'action':'stop'})
        except Exception as e:record['stop_error']=str(e)
    raise
finally:
    record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],e1=n['external_axes']['E1'],baseline=record['baseline'],steps=record['steps'],report=str(path))))
