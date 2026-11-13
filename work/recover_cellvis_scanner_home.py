"""One supervised empty-arm clearance after the scanner seating interruption."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
from proof_lift_plate import api
from draggo import DragGoRPC
from home_squid_transfer import checked
from scope_step_trial import near
from cellvis24_squid_route import geometry
from run_record_io import write_run_record

folder=ROOT/'operator_ui/reports/plate_session/cellvis24_recoveries'/str(time.time_ns())
folder.mkdir(parents=True)
record=dict(status='checking',at=time.time(),commands=[],plate_absent=True,
    operator_observation='User: i removed the plate continue; existing clear HOME vertical path and E-stop supervision.',
    prior_failure='operator_ui/reports/plate_session/cellvis24_scanner_returns/2094a75669894864bf1efdfcb4f2c807/return_home.json')
def save():write_run_record(folder/'run.json',record)
def check():
    s=api('state');n=DragGoRPC('192.168.201.220').info()
    record.setdefault('samples',[]).append(dict(at=time.time(),state=s,native=n));save()
    if s['sequence']['active'] or not s['robot'].get('connected') or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
        raise RuntimeError('Expected stationary fault-free Auto; no recovery retry.')
    return s,n
def send(path,body):
    item=dict(path=path,body=body,status='dispatching');record['commands'].append(item);save()
    r=api(path,body);item.update(status='returned',result=r);save()
    if not r.get('ok') or r.get('recovered'):raise RuntimeError('Uncertain command; no retry.')
    return r
try:
    if not api('state')['robot'].get('connected'):send('connect',dict(ip='192.168.201.220'))
    s,n=check();record['before']=s;save()
    near(s['robot']['pose_mm'],dict(X=312.75,Y=-65.998,Z=75.697,Rz=89.969),.05)
    if n['external_axes']['E1']>1:raise RuntimeError('Confirmed-empty starting jaw state changed.')
    if s['robot']['program_state']['state']!='paused':raise RuntimeError('Expected paused program changed.')
    # Stop before enable: never resume the interrupted program.
    send('program',dict(action='stop'));s,n=check()
    if not s['robot']['enabled']:send('enable',dict(confirm=True))
    check();send('program',dict(action='start'))
    s,n=check()
    if s['robot']['program_state']['state']!='running':raise RuntimeError('Startup not verified.')
    send('gripper',dict(action='move',e1=28,speed=5));s,n=check()
    if abs(n['external_axes']['E1']-28)>.07:raise RuntimeError('Opening not verified.')
    g=geometry();cfg=g['cfg'];pose=s['robot']['pose_mm'];clear=dict(pose,Z=pose['Z']+30)
    for target in (clear,g['clearance']):
        s,n=check();r=s['robot']
        if abs(n['external_axes']['E1']-28)>.07:raise RuntimeError('Jaws changed.')
        checked(r['pose_mm'],[target],r['joints'],cfg,g['envelope'])
        send('move',dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=5,interpolation='linear'))
        s,n=check();near(s['robot']['pose_mm'],target,.05)
    record.update(status='empty_clearance_plate_absent',final=s['robot'],final_native=n)
except BaseException as error:
    record.update(status='stopped_or_uncertain',error=str(error));raise
finally:
    record['finished_at']=time.time();save();print(json.dumps(dict(status=record['status'],record=str(folder/'run.json'))),flush=True)
