"""One operator-authorized empty-controller preparation, no fault reset/retry."""
import sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
from proof_lift_plate import api
from draggo import DragGoRPC

folder=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'/('prepare_'+str(time.time_ns()))
folder.mkdir();record=dict(status='checking',authorization='Continue calibration; operator confirms plate supported in HOME and empty jaws; standing route/hands/E-stop confirmation.',commands=[])
def save():(folder/'run.json').write_text(json.dumps(record,indent=2))
def check():
    s=api('state');n=DragGoRPC('192.168.201.220').info()
    if s['sequence']['active'] or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
        raise RuntimeError('Preparation requires inactive stationary fault-free Auto.')
    if s['robot'].get('errors') or not s['robot'].get('connected'):raise RuntimeError('Unavailable controller or fault.')
    p=s['robot']['pose_mm']
    if any(abs(p[k]-v)>.15 for k,v in dict(X=279.379,Y=25.829,Z=289.129,Rz=-3.88).items()):
        raise RuntimeError('Arm moved from camera observation pose.')
    if n['external_axes']['E1']>1:raise RuntimeError('Confirmed-empty jaw state changed.')
    return s,n
def send(path,body):
    record['commands'].append(dict(path=path,body=body,status='dispatching'));save()
    r=api(path,body);record['commands'][-1].update(result=r,status='returned');save()
    if not r.get('ok') or r.get('recovered'):raise RuntimeError('Preparation rejected or uncertain; no retry.')
try:
    if not api('state')['robot'].get('connected'):send('connect',{'ip':'192.168.201.220'})
    s,n=check();record['before']=dict(state=s,native=n);save()
    if s['robot']['program_state']['state']!='stopped':raise RuntimeError('Expected stopped program; do not resume.')
    if not s['robot']['enabled']:send('enable',{'confirm':True})
    s,n=check()
    if not s['robot']['enabled']:raise RuntimeError('Enable not confirmed.')
    send('program',{'action':'start'})
    s,n=check()
    if s['robot']['program_state']['state']!='running' or not s['robot']['lua_app_initialized']:
        raise RuntimeError('Running initialized Auto not confirmed.')
    record.update(status='prepared',after=dict(state=s,native=n))
except BaseException as e:
    record.update(status='failed_or_uncertain',error=str(e));raise
finally:
    save();print(json.dumps(dict(status=record['status'],record=str(folder/'run.json'))))
