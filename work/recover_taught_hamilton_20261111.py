"""Confirmed empty-arm recovery for this trial; no automatic retry."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
from run_cellvis24_workflow import api
from draggo import DragGoRPC
from scope_step_trial import near
from cellvis24_squid_route import geometry
from home_squid_transfer import checked
from repeat_calibration_hamilton import return_idle
from run_record_io import write_run_record

parser=argparse.ArgumentParser();parser.add_argument('--clear-only',action='store_true');args=parser.parse_args()
folder=ROOT/'operator_ui/reports/plate_session/cellvis24_recoveries'/('taught_'+str(time.time_ns()))
folder.mkdir();record=dict(status='checking',at=time.time(),commands=[],samples=[],
    authorization='Operator confirmed completely free, jaws empty, Cellvis plate flat in HOME, vertical path to Z300 clear, hands clear and E-stop supervised after the collision.')
def save():write_run_record(folder/'run.json',record)
def read(allow_fault=False):
    s=api('state');n=DragGoRPC('192.168.201.220').info()
    record['samples'].append(dict(at=time.time(),state=s,native=n));save()
    if s['sequence']['active'] or not s['robot'].get('connected') or any(n.get(k,True) for k in ('moving','emergency','drag','manual')):
        raise RuntimeError('State changed; no recovery sent.')
    if not allow_fault and (n.get('error',True) or s['robot'].get('errors')):raise RuntimeError('Controller remains faulted; no retry.')
    return s,n
def send(path,body):
    item=dict(path=path,body=body,status='dispatching');record['commands'].append(item);save()
    result=api(path,body);item.update(status='returned',result=result);save()
    if result.get('ok') is not True or result.get('recovered'):raise RuntimeError('Command uncertain; no retry.')
    return result
try:
    if not api('state')['robot'].get('connected'):send('connect',dict(ip='192.168.201.220'))
    s,n=read(args.clear_only)
    near(s['robot']['pose_mm'],dict(X=292.328,Y=68.788,Z=110.64,Rz=6.023),.1)
    if n['external_axes']['E1']>1:raise RuntimeError('Confirmed empty starting state changed.')
    if args.clear_only:
        if s['robot']['program_state']['state']!='stopped' or s['robot']['enabled']:raise RuntimeError('Expected stopped disabled state.')
        if s['robot']['errors']:send('clear_errors',dict(confirm=True))
        s,n=read();record.update(status='faults_cleared_no_motion',final=s)
    else:
        if s['robot']['program_state']['state'] not in ('stopped','running'):raise RuntimeError('Unexpected program state.')
        if s['robot']['program_state']['state']=='stopped':
            if not s['robot']['enabled']:send('enable',dict(confirm=True))
            read();send('program',dict(action='start'));read()
        elif not s['robot']['enabled']:raise RuntimeError('Running program is disabled; no automatic resume.')
        send('gripper',dict(action='move',e1=28,speed=5));s,n=read()
        if abs(n['external_axes']['E1']-28)>.07:raise RuntimeError('Opening not verified.')
        g=geometry();r=s['robot'];up=dict(r['pose_mm'],Z=300)
        checked(r['pose_mm'],[up],r['joints'],g['cfg'],g['envelope'])
        send('move',dict(x=up['X'],y=up['Y'],z=up['Z'],rz=up['Rz'],speed=5,interpolation='linear'))
        s,n=read();near(s['robot']['pose_mm'],up,.05)
        return_idle();s,n=read();record.update(status='at_idle',final=s)
except BaseException as error:
    record.update(status='stopped_or_uncertain',error=str(error));raise
finally:
    record['finished_at']=time.time();save();print(json.dumps(dict(status=record['status'],record=str(folder/'run.json'))),flush=True)
