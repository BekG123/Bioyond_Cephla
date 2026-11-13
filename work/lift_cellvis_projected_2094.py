"""Single requested5mm proof lift; grip unchanged; no scanner travel/retry."""
import json,time,math,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
from proof_lift_plate import api
from draggo import DragGoRPC
from autonomy import check_path
from scope_step_trial import near
from run_record_io import write_run_record

source=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/2094a75669894864bf1efdfcb4f2c807/supervised_grip/run.json'
raw=source.read_bytes();grip=json.loads(raw)
if grip['status']!='closure_completed_grasp_unverified':raise RuntimeError('Completed grip required.')
if not 0<=time.time()-grip['finished_at']<=1800:raise RuntimeError('Grip record stale.')
start=grip['final']['robot']['pose_mm'];goal=dict(start,Z=round(start['Z']+5,3))
folder=source.parent/'proof_lift';folder.mkdir(exist_ok=False);path=folder/'run.json'
record=dict(status='checking',at=time.time(),source=str(source),source_sha256=hashlib.sha256(raw).hexdigest(),
            target=goal,speed=5,motion_sent=False,lift_mm=5,gripper_commands=False,
            authorization='User confirmed even contact/flat plate; requested5mm lift at5 then scanner at137.')
def save():write_run_record(path,record)
def require(r):
    if r.get('ok') is not True or r.get('recovered'):raise RuntimeError(str(r))
    return r
def check(pose):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    if (not r.get('connected') or r.get('errors') or not r.get('enabled') or r.get('control_mode',{}).get('mode')!='auto'
            or r.get('program_state',{}).get('state')!='running' or s['sequence'].get('active')):raise RuntimeError('Controller not ready.')
    if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):raise RuntimeError('Native state not ready.')
    if not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-3.9)>.07:raise RuntimeError('Grip changed.')
    near(r['pose_mm'],pose,.05);return s,n
try:
    if not api('state')['robot'].get('connected'):require(api('connect',{'ip':'192.168.201.220'}))
    s,n=check(start);record.update(before=s,before_native=n)
    cfg=api('robot_params');env={k:[s['envelope'][k]['min'],s['envelope'][k]['max']] for k in ('X','Y','Z')}
    q=check_path(start,goal,s['robot']['joints'],cfg,env)
    record.update(cfg=cfg,envelope=env,expected_joints=q,motion_sent=True);save()
    record['response']=require(api('move',dict(x=goal['X'],y=goal['Y'],z=goal['Z'],rz=goal['Rz'],speed=5,interpolation='linear')));save()
    s,n=check(goal);record.update(status='lift_completed_retention_unverified',final=s,final_native=n,torque_report=require(api('gripper',{'action':'torque'})))
except BaseException as error:
    record.update(status='stopped_or_uncertain',error=str(error))
    if record['motion_sent']:
        try:record['stop_response']=api('program',{'action':'stop'})
        except Exception as stop:record['stop_error']=str(stop)
    raise
finally:
    record['finished_at']=time.time();save();print(json.dumps(dict(status=record['status'],record=str(path),target=goal)),flush=True)
