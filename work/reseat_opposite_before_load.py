"""Return this completed proof lift five mm and release before host reload."""
import sys,json,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'operator_ui'))
from run_cellvis24_workflow import api
from draggo import DragGoRPC
from scope_step_trial import near
from gripper_closure import grip_feedback_matches
from holder_contact_monitor import holder_ok
from cellvis24_scanner_return import sha
from run_record_io import write_run_record
from barcode_opposite_pickup import source_data

folder=root/'operator_ui/reports/plate_session/barcode_opposite_trials/1eb629a74b4f4029b2fd0bab283d0348'
source,d,g=source_data(folder/'run.json')
pickup=folder/'pickup.json';p=json.loads(pickup.read_bytes())
if p['status']!='proof_lift_completed_retention_pending' or p['source_sha256']!=sha(source):raise RuntimeError('Completed matching proof lift required.')
out=folder/'reseat_before_load.json'
r=dict(status='checking',source=str(pickup),source_sha256=sha(pickup),motion_sent=False,
       observation='Operator confirmed rotated plate level, securely held and free after proof lift.',steps=[])
def save():write_run_record(out,r)
def require(v):
    if not v.get('ok') or v.get('recovered') or v.get('gripper_warning'):raise RuntimeError(str(v))
    return v
def check(pose,e1):
    s=api('state');b=s['robot'];n=DragGoRPC('192.168.201.220').info()
    if s['sequence']['active'] or not b.get('connected') or b.get('errors') or not b.get('enabled') or b.get('program_state',{}).get('state')!='running' or b.get('control_mode',{}).get('mode')!='auto' or any(n.get(k,True) for k in ('moving','manual','error','emergency','drag')):raise RuntimeError('Controller not ready.')
    near(b['pose_mm'],pose,.05)
    if not holder_ok(n['external_axes']['E2'],181.77,True):raise RuntimeError('Holder changed.')
    if e1 is not None and not (abs(n['external_axes']['E1']-28)<=.07 if e1==28 else grip_feedback_matches(n['external_axes']['E1'],e1)):raise RuntimeError('Jaw changed.')
    return s,n
with out.open('x') as f:json.dump(r,f)
try:
    if not api('state')['robot'].get('connected'):require(api('connect',{'ip':'192.168.201.220'}))
    check(p['lift_target'],3.9);r['motion_sent']=True;save()
    q=g['seat'];r['steps'].append(require(api('move',dict(x=q['X'],y=q['Y'],z=q['Z'],rz=q['Rz'],speed=5,interpolation='linear'))));save()
    check(q,3.9)
    r['steps'].append(require(api('gripper',dict(action='move',e1=28,speed=5))));save()
    for _ in range(3):s,n=check(q,28);time.sleep(.1)
    r.update(status='released_at_rotated_HOME',final=s,final_native=n,payload='empty')
except BaseException as e:
    r.update(status='stopped_or_uncertain',error=str(e))
    if r['motion_sent']:
        try:r['stop']=api('program',{'action':'stop'})
        except Exception as stop:r['stop_error']=str(stop)
    raise
finally:r['finished_at']=time.time();save();print(json.dumps({'status':r['status'],'record':str(out)}))
