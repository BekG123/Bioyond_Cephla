"""Session-specific authorized empty-arm preparation; no fault reset/retry."""
import sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
from proof_lift_plate import api
from draggo import DragGoRPC
from scope_step_trial import near
from run_record_io import write_run_record
from home_squid_transfer import checked
from cellvis24_calibration import IDLE,OBSERVATION
from run_cellvis24_workflow import prepare_calibration
from repeat_calibration_hamilton import return_idle

folder=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'/('adjustment_setup_'+str(time.time_ns()))
folder.mkdir();record=dict(status='checking',at=time.time(),commands=[],
    authorization='Fresh retry after correcting erroneous stationary-only queue monitor; jaws stayed open28 at Z299.644, no fault, no plate contact; standing empty-gripper and clear-route/E-stop confirmation.')
def save():write_run_record(folder/'run.json',record)
def check():
    s=api('state');n=DragGoRPC('192.168.201.220').info()
    if s['sequence']['active'] or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
        raise RuntimeError('Expected inactive fault-free stationary Auto; no reset.')
    if not s['robot'].get('connected') or s['robot'].get('errors'):raise RuntimeError('No healthy connection.')
    return s,n
def send(path,body):
    record['commands'].append(dict(path=path,body=body,status='dispatching'));save()
    r=api(path,body);record['commands'][-1].update(status='returned',result=r);save()
    if not r.get('ok') or r.get('recovered'):raise RuntimeError('Command rejected or uncertain; no retry.')
    return r
try:
    if not api('state')['robot'].get('connected'):send('connect',{'ip':'192.168.201.220'})
    s,n=check();record['before']=s;save()
    near(s['robot']['pose_mm'],dict(X=312.666,Y=-65.931,Z=299.644,Rz=90.063),.05)
    if abs(n['external_axes']['E1']-28)>.07 or s['robot']['program_state']['state']!='stopped':raise RuntimeError('Expected confirmed-empty stopped setup changed.')
    ui=api('researcher/api/lacry/state')
    if ui['running']['active'] or ui.get('pending'):raise RuntimeError('Another workflow owns console.')
    if not s['robot']['enabled']:send('enable',{'confirm':True})
    check();send('program',{'action':'start'})
    s,n=check()
    if s['robot']['program_state']['state']!='running' or not s['robot'].get('lua_app_initialized'):raise RuntimeError('Program did not initialize.')
    return_idle()
    prepare_calibration()  # Opens empty jaws and restores holder at IDLE.
    cfg=json.loads((ROOT/'operator_ui/robot_params.json').read_text(encoding='utf-8-sig'))
    for point in [dict(IDLE,Z=OBSERVATION['Z']),OBSERVATION]:
        s,n=check();r=s['robot']
        if abs(n['external_axes']['E1']-28)>.07:raise RuntimeError('Open jaws changed.')
        envelope={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
        checked(r['pose_mm'],[point],r['joints'],cfg,envelope)
        send('move',dict(x=point['X'],y=point['Y'],z=point['Z'],rz=point['Rz'],speed=5,interpolation='linear'))
        s,n=check();near(s['robot']['pose_mm'],point,.05)
    record.update(status='ready_for_images',final=api('state'))
except BaseException as error:
    record.update(status='stopped_or_uncertain',error=str(error))
    # No resend. Existing move/IDLE executors handle their own motion faults.
    raise
finally:record['finished_at']=time.time();save();print(json.dumps(dict(status=record['status'],record=str(folder/'run.json'))),flush=True)

