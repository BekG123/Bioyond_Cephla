"""One-shot, receipt-bound Cellvis Hamilton handling after the first delivery.

Reuses the pinned Cellvis Lua route. Stops held after reseating in HOME for
first-plate support inspection; no release on an assumed support state.
"""
import hashlib
import json
import math
import time
from copy import deepcopy

from autonomy import TransferError, check_path
from cellvis24_hamilton_route import FOLDER, reference, validate_route, instrument_ready, PLAN_SHA
from gripper_closure import closure_commands
from home_hamilton_exchange import native
from scope_step_trial import preflight, near
from trajectory_queue import LuaTrajectory
from run_record_io import write_run_record

PHASES={
    'hamilton_empty_return':('hamilton_release_trial.json','released_at_hamilton',28),
    'hamilton_retrieve':('hamilton_empty_return.json','completed',28),
}


def plan(service,cfg,phase):
    if phase not in PHASES:raise TransferError('Unknown Cellvis handling phase.')
    output=FOLDER/(phase+'.json')
    if output.exists():raise TransferError('This phase was already attempted; inspect its receipt, no retry.')
    filename,status,e1=PHASES[phase];source=FOLDER/filename;data=json.loads(source.read_bytes())
    if data.get('status')!=status:raise TransferError('Previous phase not completed.')
    p=reference();s=preflight(service);n=native(service)
    if n['moving'] or not all(math.isfinite(n['external_axes'][k]) for k in ('E1','E2')) or abs(n['external_axes']['E1']-e1)>.1:
        raise TransferError('Unexpected arm/jaw state.')
    if abs(n['external_axes']['E2']-90.71661229181757)>.5:
        raise TransferError('HOME holder changed before its approach.')
    near(s['pose_mm'],data['final']['pose_mm'],.05)
    short=json.loads((FOLDER/'short_side_grip_lift_trial.json').read_bytes())
    seat={k:round(short['plan']['seat'][k],2) for k in ('X','Y','Z','Rz')}
    clearance=dict(seat,Z=round(seat['Z']+30,2))
    forward=p['routes']['forward'];reverse=p['routes']['reverse'];q=s['joints']
    if phase=='hamilton_retrieve':
        near(s['pose_mm'],clearance,.05)
        q=check_path(s['pose_mm'],forward['start'],q,cfg,service.envelope)
        # Z changes must be reflected in the native prismatic joint state.
        q['J1']=forward['start']['Z']+(s['joints']['J1']-s['pose_mm']['Z'])
        q=validate_route(forward['start'],forward['points'],q,cfg,service.envelope,'cellvis24_hamilton_forward')
    else:near(s['pose_mm'],reverse['start'],.05)
    q=validate_route(reverse['start'],reverse['points'],q,cfg,service.envelope,'cellvis24_hamilton_reverse')
    goal=clearance if phase=='hamilton_empty_return' else seat
    check_path(reverse['points'][-1],goal,q,cfg,service.envelope)
    capability=LuaTrajectory(service).capability()
    if not capability.get('available') or capability.get('version')!=220109:
        raise TransferError('Mixed-speed Lua queue220109 required.')
    return dict(phase=phase,source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                route_sha256=PLAN_SHA,start=s['pose_mm'],joints=s['joints'],e1=e1,
                seat=seat,clearance=clearance,forward=forward['points'],reverse=reverse['points'],
                forward_speeds=forward['segment_speeds'],reverse_speeds=reverse['segment_speeds'],
                hamilton=instrument_ready(),stop_held_in_HOME=phase=='hamilton_retrieve')


def execute(run,service,cfg,approved):
    fresh=plan(service,cfg,approved['phase'])
    for key in ('phase','source','source_sha256','route_sha256','e1','seat','clearance','forward','reverse','forward_speeds','reverse_speeds','stop_held_in_HOME'):
        if approved.get(key)!=fresh[key]:raise TransferError('Cellvis handling plan changed: '+key)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Starting joint configuration changed.')
    output=FOLDER/(fresh['phase']+'.json');expected_e1=fresh['e1']
    record=dict(status='started',plan=deepcopy(fresh),steps=[],samples=[],motion_sent=False)
    with output.open('x') as stream:json.dump(record,stream,indent=2)
    def save():write_run_record(output,record)
    def check(stationary=False,check_jaws=True):
        s=preflight(service);n=native(service)
        if run.stopped() or (stationary and n['moving']):raise TransferError('Handling stopped or motion unsettled.')
        axes=n['external_axes']
        if not all(math.isfinite(axes[k]) for k in ('E1','E2')):
            raise TransferError('Invalid external-axis feedback.')
        if check_jaws and abs(axes['E1']-expected_e1)>.1:raise TransferError('Unexpected jaw position.')
        if abs(axes['E2']-90.71661229181757)>.5:raise TransferError('HOME holder moved before approach.')
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=axes));save()
        return s,n
    def queue(label,points,speed,**flags):
        s,_=check(True);run.say(label)
        step=dict(label=label,status='dispatching',points=points,speed=speed);record['steps'].append(step)
        record['motion_sent']=True;save()
        result=LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],points,cfg,speed,
                                            lambda *args:check(),reviewed=True,**flags)
        if not result.get('ok') or result.get('recovered'):raise TransferError('Uncertain queue; no retry.')
        s,_=check(True);near(s['pose_mm'],points[-1],.1)
        step.update(status='completed',response=result);save()
    def close(target,speed):
        nonlocal expected_e1
        s,_=check(True);near(s['pose_mm'],fresh['forward'][-1],.05)
        step=dict(label='Cellvis short-side grip',target=target,speed=speed,status='dispatching');record['steps'].append(step)
        record['motion_sent']=True;save()
        result=service.move_gripper(target,speed);step['response']=result;save()
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
            raise TransferError('Grip failed or uncertain; no lift/retry.')
        deadline=time.monotonic()+2;stable=0
        while stable<3:
            current,n=check(True,False);near(current['pose_mm'],s['pose_mm'],.05)
            stable=stable+1 if abs(n['external_axes']['E1']-target)<=.07 else 0
            if time.monotonic()>deadline:raise TransferError('Grip did not settle; no lift.')
            if stable<3:time.sleep(.1)
        expected_e1=target;step.update(status='completed',actual_e1=n['external_axes']['E1']);save()
    try:
        check(True);instrument_ready()
        if fresh['phase']=='hamilton_retrieve':
            origin=reference()['routes']['forward']['start']
            queue('Empty HOME connector to Hamilton route',[origin],5,home_transit=True)
            queue('Empty Cellvis approach to Hamilton',fresh['forward'],137,
                  hamilton_short_side='cellvis24_hamilton_forward',segment_speeds=fresh['forward_speeds'])
            for command in closure_commands(28,25):close(command['target_e1_mm'],command['speed'])
        queue('Cellvis Hamilton departure and direct HOME return',fresh['reverse'],137,
              hamilton_short_side='cellvis24_hamilton_reverse',segment_speeds=fresh['reverse_speeds'])
        if fresh['phase']=='hamilton_empty_return':
            queue('Empty arm to HOME clearance',[fresh['clearance']],137,home_transit=True,home_speed137=True)
        else:
            queue('Reseat Cellvis in HOME; keep jaws closed',[fresh['seat']],5,home_transit=True)
        s,n=check(True);record.update(status='completed',final=s,final_native=n,
            payload='held' if fresh['phase']=='hamilton_retrieve' else 'empty',
            support_inspection_required=fresh['phase']=='hamilton_retrieve')
        return dict(ok=True,record=str(output),pose_mm=s['pose_mm'],payload=record['payload'],support_inspection_required=record['support_inspection_required'])
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error))
        if record['motion_sent']:
            try:record['stop_response']=service.program('stop')
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:record['finished_at']=time.time();save()
