"""Confirmed empty-arm recovery from the first taught Hamilton turn.

No loaded restart, native backtracking, automatic experiment retry, or arbitrary
target API. Existing geometry, IK, queue monitoring and controller owner are used.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4

from autonomy import TransferError, check_path
from draggo import DragGoRPC
from hamilton_opposite_wrist_route import build
from run_record_io import write_run_record
from scope_step_trial import near
from trajectory_queue import LuaTrajectory, prepare_points

FOLDER=Path(__file__).resolve().parent/'reports/plate_session/empty_home_recovery'
HOME=dict(X=312.5,Y=-66.3,Z=105.72,Rz=89.84)

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def raw(service):
    return DragGoRPC(service._endpoint_addr()[0]).info()

def stopped_state(service):
    s=service.status();n=raw(service)
    if not s.get('connected') or not s.get('ok') or s.get('program_state',{}).get('state')!='stopped':
        raise TransferError('Empty HOME recovery requires a connected, stopped program.')
    if any(n.get(k,True) for k in ('moving','emergency','drag')) or n.get('manual'):
        raise TransferError('Stop motion/end hand-guiding before recovery; Auto is required.')
    if not service.envelope_enabled:raise TransferError('Workspace checks must remain enabled.')
    for k in ('E1','E2'):
        if type(n.get('external_axes',{}).get(k)) not in (int,float) or not math.isfinite(n['external_axes'][k]):
            raise TransferError('Fresh finite external-axis feedback required.')
    return s,n

def route(state,cfg,envelope):
    taught=build();a,b=taught['routes']['forward']['points'][:2]
    p=state['pose_mm']
    if cfg!=taught['config']:raise TransferError('Recovery robot geometry changed.')
    if any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for k in HOME):
        raise TransferError('Invalid recovery position.')
    # Only the first high turn: no generic claim that every pose can reach HOME.
    if not (abs(p['Z']-a['Z'])<=.5 and a['Rz']-.5<=p['Rz']<=b['Rz']+2):
        raise TransferError('No commissioned empty recovery from this position.')
    t=max(0,min(1,(p['Rz']-a['Rz'])/(b['Rz']-a['Rz'])))
    if math.hypot(p['X']-(a['X']+t*(b['X']-a['X'])),p['Y']-(a['Y']+t*(b['Y']-a['Y'])))>5:
        raise TransferError('Arm is outside the first-turn recovery corridor.')
    # Retrace the turn at its taught height, then remain above the seated plate.
    targets=[a,dict(HOME,Z=a['Z']),HOME]
    points=[];origin={k:p[k] for k in HOME}
    for target in targets:
        count=max(1,math.ceil(abs(target['Rz']-origin['Rz'])/5),
                  math.ceil(math.dist([origin[k] for k in ('X','Y','Z')],[target[k] for k in ('X','Y','Z')])/5))
        points.extend({k:round(origin[k]+(target[k]-origin[k])*i/count,2) for k in HOME} for i in range(1,count+1))
        origin=target
    points,joints=prepare_points(p,state['joints'],points,cfg,reviewed=True)
    prev=p;q=state['joints']
    for point in points:
        q=check_path(prev,point,q,cfg,envelope);prev=point
    return points,fingerprint(taught)

def preview(service,cfg):
    s,n=stopped_state(service)
    # Empty recovery stays above the holder, without pickup or holder rotation.
    # Bind its measured angle instead of requiring a pickup orientation.
    if abs(n['external_axes']['E2'])>360:
        raise TransferError('Holder feedback is outside its published travel range.')
    points,route_hash=route(s,cfg,service.envelope)
    return dict(dispatch='empty_home_recovery',actions=['recover_empty_home'],
        labels=['Recover empty arm to HOME'],summary='Recover the empty arm to HOME clearance and open the jaws. The experiment stays stopped.',
        requirements=['The plate has been removed from the jaws and is flat and supported in HOME.',
            'The obstruction is removed; the reverse turn and HOME clearance path are clear.',
            'The arm is released, hands are clear, and the E-stop is supervised.',
            'Startup closes empty jaws. A held plate is not allowed. No experiment retry is included.'],
        steps=[dict(kind='recover',label=x) for x in ('Clear fault and prepare empty arm','Return slowly to HOME','Open jaws and verify')],
        start=s['pose_mm'],joints=s['joints'],external_axes=n['external_axes'],
        cfg=deepcopy(cfg),envelope={k:list(v) for k,v in service.envelope.items()},points=points,route_hash=route_hash,
        speed=5,at=time.time(),payload='empty_requires_operator_confirmation')

def verify_plan(service,cfg,plan):
    if not 0<=time.time()-plan['at']<=300:raise TransferError('Recovery plan expired.')
    fresh=preview(service,cfg)
    near(fresh['start'],plan['start'],.05)
    if any(abs(fresh['joints'][k]-v)>.1 for k,v in plan['joints'].items()):raise TransferError('Recovery joints changed.')
    if any(abs(fresh['external_axes'][k]-plan['external_axes'][k])>.1 for k in ('E1','E2')):
        raise TransferError('Recovery payload/holder feedback changed; confirm again.')
    if fresh['route_hash']!=plan['route_hash'] or fresh['cfg']!=plan['cfg'] or fresh['envelope']!=plan['envelope']:
        raise TransferError('Recovery geometry changed.')
    return fresh

def execute(run,service,cfg,plan,empty_confirmed=False):
    if empty_confirmed is not True:raise TransferError('Explicit empty-jaw confirmation required; loaded recovery is unavailable.')
    plan=verify_plan(service,cfg,plan)
    FOLDER.mkdir(parents=True,exist_ok=True);path=FOLDER/(uuid4().hex+'.json')
    record=dict(status='starting',at=time.time(),plan=plan,payload_confirmed_empty=True,
                program_start_sent=False,motion_sent=False,automatic_retry=False,events=[])
    def save(event,**data):
        record['events'].append(dict(at=time.time(),event=event,**data));write_run_record(path,record)
    def require(result):
        if not result.get('ok'):raise TransferError(str(result.get('error','Recovery command failed; no retry.')))
        return result
    def check(*args,expected=0):
        if run.stopped():raise TransferError('Recovery stopped.')
        s=service.status();n=raw(service)
        if not s.get('enabled') or s.get('errors') or s['program_state']['state']!='running' or any(n.get(k,True) for k in ('error','emergency','drag','manual')):
            raise TransferError('Controller not healthy during recovery.')
        if abs(n['external_axes']['E2']-plan['external_axes']['E2'])>.5:raise TransferError('Holder moved during recovery.')
        if abs(n['external_axes']['E1']-expected)>.15:raise TransferError('Unexpected jaw position; no further recovery motion.')
        return s
    try:
        save('confirmed')
        if service.status().get('errors'):
            if run.stopped():raise TransferError('Recovery stopped before fault clear.')
            save('clear_requested');require(service.clear_errors(confirmed=True))
        if service.status().get('errors'):raise TransferError('Fault remains; no retry.')
        if run.stopped():raise TransferError('Recovery stopped before enable.')
        if not service.status().get('enabled'):
            save('enable_requested');require(service.set_enable(True,confirmed=True))
        near(service.status()['pose_mm'],plan['start'],.05)
        if run.stopped():raise TransferError('Recovery stopped before startup.')
        record['program_start_sent']=True;save('empty_startup_requested')
        # Force acknowledges stale historical torque only AFTER explicit empty confirmation.
        require(service.program('start',force=True))
        s=check();near(s['pose_mm'],plan['start'],.05)
        run.say('Returning empty arm slowly to HOME clearance.')
        record['motion_sent']=True;save('return_requested')
        require(LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],plan['points'],cfg,5,check,reviewed=True))
        s=check();near(s['pose_mm'],HOME,.05)
        if run.stopped():raise TransferError('Recovery stopped before opening jaws.')
        run.say('Opening empty jaws at HOME.');save('open_requested')
        require(service.move_gripper(28,5))
        for _ in range(3):
            s=check(expected=28);near(s['pose_mm'],HOME,.05);time.sleep(.1)
        record.update(status='completed',final=s,experiment_retried=False);save('verified')
        return dict(ok=True,record=str(path),status='empty_at_HOME',pose_mm=s['pose_mm'],experiment_retried=False)
    except BaseException as e:
        record.update(status='failed_or_uncertain',error=str(e));save('failed')
        if record['program_start_sent']:
            try:record['stop_result']=service.program('stop')
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();write_run_record(path,record)

def start(agent,plan):
    service=agent.backend.s;cfg=agent.backend.params();run=agent.get_runner()
    if run.active or run.reserved:raise TransferError('Another workflow owns the arm.')
    verify_plan(service,cfg,plan)
    with agent.lock:
        if not agent.pending or agent.pending['id']!=plan['id']:raise TransferError('Recovery approval already consumed.')
        agent.pending=None
        agent.run_meta=dict(name='Empty arm recovery',total_steps=3)
        agent.run_state=dict(active=True,step='Recover to HOME',done=[],ok=None,error='',message='Recovering the confirmed empty arm.')
    result=run.start('empty_home_recovery',execute,service,cfg,plan,True)
    if not result.get('ok'):
        with agent.lock:agent.run_state.update(active=False,ok=False,error=result.get('error','Recovery did not start.'))
        raise TransferError(result.get('error','Recovery did not start.'))
    worker=run._thread
    def finish():
        worker.join();snapshot=run.snapshot();ok=(snapshot.get('result') or {}).get('ok') is True and snapshot.get('state')=='done'
        message=('Empty arm is at HOME with jaws open. The experiment remains stopped; request a fresh plan to retry.' if ok else
                 'Recovery stopped: '+str((snapshot.get('result') or {}).get('error','completion uncertain')))
        with agent.lock:agent.run_state.update(active=False,ok=ok,step=None,done=['Recovered to HOME'] if ok else [],message=message,error='' if ok else message)
        agent._say('lacry',message)
    threading.Thread(target=finish,daemon=True,name='empty-home-recovery-result').start()
    return dict(result,message='Recovering the confirmed empty arm to HOME.')
