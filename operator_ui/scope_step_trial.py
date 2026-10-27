"""One reviewed Home-to-scope trial, individual MoveL calls at speed 40."""
import hashlib
import json
import math
from pathlib import Path
import time

from autonomy import TransferError, check_path, wrap
from trajectory_queue import prepare_points, checksum

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'operator_ui/reports/squid/home_scope_solved_20261017T125835Z_f3c36d/plan.json'
OUTPUT=PLAN.with_name('stepwise40_trial.json')
KEYS=('X','Y','Z','Rz')


def near(actual,target,tolerance):
    for k in KEYS:
        delta=actual[k]-target[k]
        if k=='Rz':delta=wrap(delta)
        if abs(delta)>tolerance:raise TransferError(f'Pose mismatch {k}: {actual[k]:.3f} versus {target[k]:.3f}')


def preflight(service):
    refusal=service._preflight()
    if refusal:raise TransferError(refusal)
    state=service.status()
    if not state.get('ok') or not state.get('connected') or state.get('errors') or not state.get('enabled') or state['control_mode']['mode']!='auto' or state['program_state']['state']!='running':
        raise TransferError('Already-running healthy Auto required; this trial never starts the controller program.')
    if not service.envelope_enabled:raise TransferError('Workspace must remain enabled.')
    return state


def review(service,cfg):
    if OUTPUT.exists():raise TransferError('This one-shot trial was already attempted; inspect its record before any retry.')
    raw=PLAN.read_bytes();plan=json.loads(raw)
    if cfg!=plan['review_params']:raise TransferError('Loaded joint policy differs from the solved plan.')
    if any(list(service.envelope[k])!=plan['envelope'][k] for k in KEYS[:3]):raise TransferError('Workspace differs from the solved plan.')
    if hashlib.sha256((ROOT/'operator_ui/points.json').read_bytes()).hexdigest()!=plan['home_source_sha256']:raise TransferError('Saved Home changed.')
    state=preflight(service);near(state['pose_mm'],plan['start'],.05)
    for k in ('J1','J2','J3','J4'):
        if abs(state['joints'][k]-plan['live_robot']['joints'][k])>.5:raise TransferError('Starting joint winding/configuration changed: '+k)
    points,q=prepare_points(plan['start'],state['joints'],plan['commanded_points'],cfg,reviewed=True)
    if checksum(points)!=plan['queue_checksum']:raise TransferError('Quantized path checksum changed.')
    previous=plan['start'];q=state['joints']
    for point in points:q=check_path(previous,point,q,cfg,service.envelope);previous=point
    e1=service.external_axes().get('E1')
    if type(e1) not in (float,int) or not math.isfinite(e1):raise TransferError('Missing gripper position feedback.')
    return dict(plan_sha256=hashlib.sha256(raw).hexdigest(),start=plan['start'],points=points,
        speed=40,executor='individual_MoveL',e1_start=e1,cfg=cfg,envelope=plan['envelope'])


def execute(run,service,cfg,approved,*,review_fn=None,output=None,label='Scope',authorization=None):
    output=Path(output) if output is not None else OUTPUT
    actual_review=(review_fn or review)(service,cfg)
    if {k:v for k,v in actual_review.items() if k!='e1_start'}!={k:v for k,v in approved.items() if k!='e1_start'}:raise TransferError('Plan changed before dispatch.')
    if abs(actual_review['e1_start']-approved['e1_start'])>.05:raise TransferError('Gripper changed before dispatch.')
    record=dict(status='started',started_at=time.time(),plan=approved,steps=[],
        authorization=authorization or 'Operator confirmed new Home connector and reverse taught route clear; arm released; E-stop supervised. Requested individual moves at speed 40.',
        gripper_commands=False,program_restart=False,lua_queue_used=False)
    with output.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def save():output.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    previous=approved['start']
    try:
        for index,point in enumerate(approved['points'],1):
            if run.stopped():raise TransferError('Stopped between individual moves.')
            preflight(service)
            if any(list(service.envelope[k])!=approved['envelope'][k] for k in KEYS[:3]):raise TransferError('Workspace changed during trial.')
            e1=service.external_axes().get('E1')
            if type(e1) not in (float,int) or abs(e1-approved['e1_start'])>.1:raise TransferError('Gripper position changed; inspect before continuing.')
            pose,q=service.pose_mm(),service.joints();near(pose,previous,.2)
            predicted=check_path(pose,point,q,cfg,service.envelope)
            run.say(f'{label} trial: move {index}/{len(approved["points"])} at speed 40: X{point["X"]:.2f} Y{point["Y"]:.2f} Z{point["Z"]:.2f} Rz{point["Rz"]:.2f}')
            step=dict(index=index,target=point,before=pose,joints_before=q,e1_before=e1,started_at=time.time())
            record['steps'].append(step);save()
            result=service.move_cartesian(point['X'],point['Y'],point['Z'],point['Rz'],speed=40,interpolation='linear')
            step.update(result=result,finished_at=time.time());save()
            if not result.get('ok') or 'recovered' in result:raise TransferError('Unconfirmed individual move; no retry: '+str(result.get('error',result)))
            if run.stopped():raise TransferError('Stopped after individual move.')
            after=preflight(service);near(after['pose_mm'],point,.2)
            for k in ('J2','J3','J4'):
                if abs(after['joints'][k]-predicted[k])>.5:raise TransferError('Unexpected joint configuration/winding: '+k)
            e1=service.external_axes().get('E1')
            if type(e1) not in (float,int) or abs(e1-approved['e1_start'])>.1:raise TransferError('Gripper position changed after move.')
            step.update(pose_after=after['pose_mm'],joints_after=after['joints'],e1_after=e1,status='arrived');save()
            run.audit('scope_step_arrived',step=step,total=len(approved['points']))
            previous=point
        record.update(status='completed',final_robot=service.status());save()
        run.say(label+' reached; individual speed-40 trial completed.','good')
        return dict(ok=True,record=str(output),moves=len(record['steps']),pose_mm=service.pose_mm(),speed=40,lua_queue_used=False)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error));save()
        try:record['stop_result']=service.program('stop')
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();save();run.audit('scope_step_trial',record=str(output),status=record['status'])
