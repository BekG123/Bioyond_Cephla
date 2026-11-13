"""Explicitly requested recovery from the stopped camera pose; no calibration."""
import sys,json,time
from pathlib import Path
from uuid import uuid4
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'operator_ui'))
from run_cellvis24_workflow import api
from run_cellvis24_scanner_hamilton import dispatch,reconnect
from repeat_calibration_hamilton import return_idle
from draggo import DragGoRPC
from scope_step_trial import near
from autonomy import check_path
from calibration_e2 import accepted
from run_record_io import write_run_record

folder=root/'operator_ui/reports/plate_session'/('scanner_retry_prepare_'+uuid4().hex)
folder.mkdir();out=folder/'run.json'
r=dict(status='checking',calibration_runs=0,at=time.time(),commands=[],
    authorization='User requested scanner retry and confirmed reset/repositioned, plate flat in HOME, jaws empty; standing route and E-stop supervision.')
def save():write_run_record(out,r)
def send(path,body):
    r['commands'].append(dict(path=path,body=body,status='dispatching'));save()
    result=api(path,body);r['commands'][-1].update(status='returned',result=result);save()
    if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):raise RuntimeError('Rejected or uncertain command; no retry.')
    return result
def read():
    s=api('state');n=DragGoRPC('192.168.201.220').info()
    if s['sequence']['active'] or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')) or s['robot'].get('errors'):raise RuntimeError('Controller not stationary/fault-free.')
    return s,n
try:
    reconnect();s,n=read();r['before']=dict(state=s,native=n);save()
    near(s['robot']['pose_mm'],dict(X=279.38,Y=25.83,Z=289.13,Rz=-3.88),.15)
    if n['external_axes']['E1']>1 or s['robot']['program_state']['state']!='stopped':raise RuntimeError('Confirmed empty/reset state changed.')
    if not s['robot']['enabled']:send('enable',{'confirm':True})
    s,n=read();near(s['robot']['pose_mm'],r['before']['state']['robot']['pose_mm'],.05)
    send('program',{'action':'start'})
    s,n=read()
    if s['robot']['program_state']['state']!='running' or not s['robot']['lua_app_initialized']:raise RuntimeError('Program not verified running.')
    near(s['robot']['pose_mm'],r['before']['state']['robot']['pose_mm'],.05)
    send('gripper',dict(action='move',e1=28,speed=5));s,n=read()
    if abs(n['external_axes']['E1']-28)>.07:raise RuntimeError('Open jaws not verified.')
    r['idle']=return_idle();save()
    r['restore']=dispatch('developer/api/home-hamilton-exchange/restore-original',dict(ready=True,empty_gripper=True,holder_clear=True),'home_hamilton_restore_original',180);save()
    s,n=read()
    if not accepted(n['external_axes']['E2']):raise RuntimeError('Original holder angle not verified.')
    target=dict(x=312.5,y=-66.3,z=75.72,rz=89.84,z_calibrated=75.72,hover_z=300)
    r['alignment']=dispatch('seq/align',target,'align',180);save()
    s,n=read();near(s['robot']['pose_mm'],dict(X=312.5,Y=-66.3,Z=300,Rz=89.84),.05)
    goal=dict(X=312.5,Y=-66.3,Z=105.72,Rz=89.84)
    cfg=api('robot_params');env={k:[s['envelope'][k]['min'],s['envelope'][k]['max']] for k in ('X','Y','Z')}
    check_path(s['robot']['pose_mm'],goal,s['robot']['joints'],cfg,env)
    send('move',dict(x=goal['X'],y=goal['Y'],z=goal['Z'],rz=goal['Rz'],speed=137,interpolation='linear'))
    s,n=read();near(s['robot']['pose_mm'],goal,.05)
    if abs(n['external_axes']['E1']-28)>.07 or not accepted(n['external_axes']['E2']):raise RuntimeError('Released HOME setup not verified.')
    r.update(status='accepted_HOME_clearance_empty',final=s,final_native=n)
except BaseException as e:r.update(status='stopped_or_uncertain',error=str(e));raise
finally:r['finished_at']=time.time();save();print(json.dumps(dict(status=r['status'],record=str(out))))
