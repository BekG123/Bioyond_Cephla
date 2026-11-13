"""Reusable, receipt-bound Cellvis closure and proof lift from the accepted trial.

All writes go through the existing Flask owner. No startup, retry, reset or
scanner motion here. Call only after the CLI's physical alignment inspection.
"""
import hashlib
import json
import math
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]
from run_cellvis24_workflow import api
from draggo import DragGoRPC
from gripper_closure import closure_plan
from holder_contact_monitor import holder_ok
from calibration_e2 import accepted
from scope_step_trial import near
from run_record_io import write_run_record

from autonomy import check_path

RUNS=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'

def trial_source(ident):
    import re
    if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident):
        raise ValueError('Expected a Cellvis trial ID (32 lowercase hex characters).')
    return RUNS/ident/'run.json'

def grip_trial(ident,execute=False):
    source=trial_source(ident)
    raw=source.read_bytes();prior=json.loads(raw)
    if prior['status']!='awaiting_open_claw_inspection' or prior.get('payload')!='empty':
        raise RuntimeError('Completed open-jaw trial required.')
    if not all(s['status']=='completed' for s in prior['steps']):raise RuntimeError('Prior motion incomplete.')
    expected=prior['final']['pose_mm'];solution=prior['resolved_calibration']['solution']
    near(expected,solution['endpoint'],.05)
    if solution.get('plate_id')!='cellvis_p24_1_5h_n' or solution['grip_e1_mm']!=3.9 or expected['Z']<75.67 or expected['Z']>75.77:
        raise RuntimeError('Cellvis accepted grip/height changed.')
    plan=closure_plan(28.,3.9)
    if not execute:
        print(json.dumps(dict(motion_started=False,expected_pose=expected,closure=plan,lift=False),indent=2));return
    if not 0<=time.time()-prior['finished_at']<=1800:raise RuntimeError('Trial receipt stale.')
    folder=source.parent/'supervised_grip';folder.mkdir(exist_ok=False)
    path=folder/'run.json'
    record=dict(status='checking',at=time.time(),source=str(source),source_sha256=hashlib.sha256(raw).hexdigest(),
                authorization='CLI operator inspected even jaw alignment, correct height and clear proof-lift path.',
                alignment_visual_acceptance='confirmed by operator before closure',
                plan=plan,expected_pose=expected,steps=[],samples=[],motion_sent=False,lift_sent=False,
                force_limits_changed=False,grasp_verified=False)
    def save():write_run_record(path,record)
    def require(result):
        if result.get('ok') is not True or result.get('recovered') or result.get('gripper_warning'):
            raise RuntimeError('Command failed or uncertain; no retry: '+str(result))
        return result
    def check(contact=False):
        s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
        if (not r.get('connected') or r.get('errors') or not r.get('enabled') or
                r.get('control_mode',{}).get('mode')!='auto' or
                r.get('program_state',{}).get('state')!='running' or not r.get('lua_app_initialized') or
                s['sequence'].get('active')):
            raise RuntimeError('Controller not healthy stationary running Auto.')
        if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
            raise RuntimeError('Native controller state not ready.')
        near(r['pose_mm'],expected,.05)
        e1,e2=(n['external_axes'][k] for k in ('E1','E2'))
        if not all(math.isfinite(x) for x in (e1,e2)):
            raise RuntimeError('Invalid external-axis feedback.')
        if not (holder_ok(e2,1.77,True) if contact else accepted(e2)):
            raise RuntimeError('Holder outside the existing accepted monitor bounds.')
        record['samples'].append(dict(at=time.time(),pose=r['pose_mm'],axes=n['external_axes']))
        save();return s,n
    try:
        if not api('state')['robot'].get('connected'):require(api('connect',{'ip':'192.168.201.220'}))
        s,n=check();record['before']=s;record['before_native']=n
        if abs(n['external_axes']['E1']-28)>.07:raise RuntimeError('Expected open empty jaws28.')
        ui=api('researcher/api/lacry/state')
        if ui.get('running',{}).get('active') or ui.get('pending'):
            raise RuntimeError('Another workflow owns the arm.')
        record['baseline']=require(api('gripper',{'action':'torque'}));save()
        previous=28.
        for command in plan['commands']:
            s,n=check(contact=record['motion_sent'])
            if abs(n['external_axes']['E1']-previous)>.07:raise RuntimeError('Jaw changed before command.')
            item=dict(command=command,status='dispatching',at=time.time())
            record['steps'].append(item);record['motion_sent']=True;save()
            item['response']=require(api('gripper',dict(action='move',e1=command['target_e1_mm'],speed=command['speed'])))
            save();stable=0;deadline=time.monotonic()+2
            while stable<3:
                s,n=check(contact=True);actual=n['external_axes']['E1']
                stable=stable+1 if abs(actual-command['target_e1_mm'])<=.07 else 0
                if time.monotonic()>deadline:raise RuntimeError('Jaw arrival not verified; stop without retry.')
                if stable<3:time.sleep(.1)
            torque=require(api('gripper',{'action':'torque'}))
            if (not torque.get('telemetry_live') or not math.isfinite(torque['e1_torque']) or
                    abs(torque['e1_position']-command['target_e1_mm'])>.07):
                raise RuntimeError('Fresh settled grip feedback unavailable.')
            item.update(status='completed',actual_e1_mm=actual,torque_report=torque);save()
            previous=command['target_e1_mm']
            print(json.dumps(dict(phase=command['phase'],actual_e1_mm=actual,speed=command['speed'],torque_report=torque)),flush=True)
        for _ in range(20):
            time.sleep(.1);s,n=check(contact=True)
            if abs(n['external_axes']['E1']-3.9)>.07:raise RuntimeError('Grip changed after closure.')
        record.update(status='closure_completed_grasp_unverified',final=s,final_native=n)
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error));save()
        if record['motion_sent']:
            try:record['stop_response']=api('program',{'action':'stop'})
            except Exception as stop:record['stop_error']=str(stop)
        raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(status=record['status'],record=str(path),lift_sent=False)),flush=True)

    return path


def proof_lift(ident):
    source=trial_source(ident).parent/"supervised_grip/run.json"
    raw=source.read_bytes();grip=json.loads(raw)
    if grip['status']!='closure_completed_grasp_unverified':raise RuntimeError('Completed grip required.')
    trial=trial_source(ident)
    if grip['source_sha256']!=hashlib.sha256(trial.read_bytes()).hexdigest():raise RuntimeError('Calibration receipt changed after grip.')
    if grip['plan']['target_e1_mm']!=3.9:raise RuntimeError('Expected accepted Cellvis grip3.9.')
    if not 0<=time.time()-grip['finished_at']<=1800:raise RuntimeError('Grip record stale.')
    start=grip['final']['robot']['pose_mm'];goal=dict(start,Z=round(start['Z']+5,3))
    folder=source.parent/'proof_lift';folder.mkdir(exist_ok=False);path=folder/'run.json'
    record=dict(status='checking',at=time.time(),source=str(source),source_sha256=hashlib.sha256(raw).hexdigest(),
                target=goal,speed=5,motion_sent=False,lift_mm=5,gripper_commands=False,
                authorization='CLI operator cleared the 5mm proof lift; grip unchanged.')
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
        if not s['envelope']['enabled']:raise RuntimeError('Workspace must be enabled.')
        ui=api('researcher/api/lacry/state')
        if ui.get('running',{}).get('active') or ui.get('pending'):raise RuntimeError('Another workflow owns the arm.')
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
    return path
