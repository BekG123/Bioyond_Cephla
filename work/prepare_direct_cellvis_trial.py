"""Prepare empty jaws after publication and preview; never travel or pick up."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
from proof_lift_plate import api
from draggo import DragGoRPC
from scope_step_trial import near
from run_record_io import write_run_record
SOURCE=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/105936a6411a46a49fc7db88e1107cd4/run.json'
folder=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'/('direct_setup_'+str(time.time_ns()))
folder.mkdir();record=dict(status='checking',at=time.time(),commands=[],authorization='User accepted plate released flat in HOME, requested new trial, published new controller program and said continue. Empty jaws remain at HOME clearance; clear jaw-opening setup and E-stop supervision carried forward.')
def save():write_run_record(folder/'run.json',record)
def check():
    s=api('state');n=DragGoRPC('192.168.201.220').info()
    record.setdefault('samples',[]).append(dict(at=time.time(),state=s,native=n));save()
    if s['sequence']['active'] or not s['robot'].get('connected') or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
        raise RuntimeError('Expected stationary fault-free Auto; no retry/reset.')
    near(s['robot']['pose_mm'],dict(X=306.2,Y=-62.88,Z=106.37,Rz=87.88),.05)
    if abs(n['external_axes']['E2']-90.71661229181757)>.5:raise RuntimeError('Holder setup changed.')
    return s,n
def send(path,body):
    item=dict(path=path,body=body,status='dispatching');record['commands'].append(item);save()
    result=api(path,body);item.update(status='returned',result=result);save()
    if not result.get('ok') or result.get('recovered'):raise RuntimeError('Command uncertain; no retry.')
    return result
try:
    if not api('state')['robot'].get('connected'):send('connect',dict(ip='192.168.201.220'))
    s,n=check()
    if s['robot']['program_state']['state'] not in ('stopped','running'):raise RuntimeError('Unexpected program state.')
    if s['robot']['program_state']['state']=='stopped':
        if n['external_axes']['E1']>1:raise RuntimeError('Expected post-publication empty jaw reading changed.')
        if not s['robot']['enabled']:send('enable',dict(confirm=True))
        check();send('program',dict(action='start'))
    s,n=check()
    if abs(n['external_axes']['E1']-28)>.07:send('gripper',dict(action='move',e1=28,speed=5))
    s,n=check()
    if abs(n['external_axes']['E1']-28)>.07:raise RuntimeError('Jaw opening not verified.')
    result=send('developer/api/cellvis24-workflow/preview',dict(stations=['hamilton'],cycles=1,source=str(SOURCE),held_hamilton_roundtrip=True,direct_hamilton=True))
    record.update(status='ready_pending_direct_clearance',plan=result['plan'],final=s,final_native=n,arm_travel_started=False)
except BaseException as error:record.update(status='stopped_or_uncertain',error=str(error));raise
finally:
    record['finished_at']=time.time();save();print(json.dumps(dict(status=record['status'],record=str(folder/'run.json'))),flush=True)
