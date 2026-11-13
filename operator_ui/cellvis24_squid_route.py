"""Receipt-bound Cellvis HOME/Squid commissioning using the saved Lua corridor.

Same transit and slow station entry/departure, with the accepted Cellvis
long-side pickup and a 2 mm height adjustment. No imaging or stage movement.
First seating/reseating releases require separately recorded observations.
"""
import hashlib
import json
import math
import secrets
import time
from pathlib import Path

from autonomy import TransferError
from calibration_e2 import accepted
from gripper_closure import closure_commands
from home_hamilton_exchange import native
from home_squid_transfer import checked
from scope_step_trial import near,preflight
from squid_adapter import SquidAdapter,native_command
from run_record_io import write_run_record

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'
PLAN=FOLDER/'squid_route_plan.json'
PLAN_SHA='aef13fb6c70533e5b00f0252e54aef2642d151846873d082bc2f880e13b30808'
PHASES={
    'deliver':('home_short_release.json','released_at_HOME_short_clearance',28),
    'continue_delivery':('squid_continuation_authorization.json','released_after_review',28),
    'deliver_after_clearance_stop':('squid_clearance_recovery_authorization.json','empty_open_after_review',28),
    'deliver_after_connector_check':('squid_connector_recovery_authorization.json','empty_open_after_review',28),
    'release_squid':('squid_deliver.json','completed',3.9),
    'empty_return':('squid_release_squid.json','completed',7),
    'retrieve':('squid_empty_return.json','completed',7),
    'release_home':('squid_retrieve.json','completed',3.9),
}


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def geometry():
    if digest(PLAN)!=PLAN_SHA:raise TransferError('Cellvis Squid plan changed.')
    g=json.loads(PLAN.read_bytes())
    if digest(ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis_p24_1_5h_n.json')!=g['profile_sha256']:
        raise TransferError('Cellvis pickup profile changed.')
    from home_squid_transfer import geometry as parent_geometry
    if hashlib.sha256(json.dumps(parent_geometry(),sort_keys=True).encode()).hexdigest()!=g['parent_geometry_sha256']:
        raise TransferError('Parent Squid geometry changed.')
    # Preserve commissioning evidence. Split only the existing straight ascent:
    # first 5mm slow for pickup/clearance, then speed137 to the SAME clearance.
    station=g['points'][-1]
    g['reverse']=[dict(station,Z=round(station['Z']+5,2))]+g['reverse']
    g['reverse_speeds']=[5,137,137,137,137]
    g['runtime_revision']='squid_departure_5mm_slow_then137_v1'
    return g


def validate_route(start,points):
    g=geometry()
    for origin,targets,speeds in [(g['proof'],g['points'],g['speeds']),
                                  (g['points'][-1],g['reverse'],g['reverse_speeds'])]:
        try:near(start,origin,.05)
        except TransferError:continue
        if points==targets:return g,speeds
    raise TransferError('Exact pinned Cellvis HOME/Squid route required.')


def check_route(start,points,joints,cfg,envelope):
    g,_=validate_route(start,points)
    if cfg!=g['cfg'] or {k:list(v) for k,v in envelope.items()}!=g['envelope']:
        raise TransferError('Cellvis Squid IK/workspace changed.')
    return checked(start,points,joints,cfg,envelope)


def instrument_ready(g):
    status=SquidAdapter(background=False).connect()
    if status.get('stage_simulated') is not False or status.get('status') not in ('idle','historical','completed'):
        raise TransferError('Physical Squid stage must remain idle.')
    position=native_command('get_position')
    from squid_loading import at_loading
    from squid_stage import REFERENCE
    reference=json.loads(REFERENCE.read_bytes())
    bridge=native_command('get_stage_reference')
    from squid_execution import digest
    if bridge.get('reference_hash')!=digest(reference) or bridge.get('controller_serial')!=reference['controller_serial']:
        raise TransferError('Squid controller/loading bridge needs updating; reconnecting does not fix missing device identity.')
    at_loading(position,g['squid_loading_position'],bridge,reference['controller_serial'])
    return position


def plan(service,cfg,phase):
    if phase not in PHASES:raise TransferError('Unknown Cellvis Squid phase.')
    if (FOLDER/('squid_'+phase+'.json')).exists():raise TransferError('Cellvis phase already attempted; inspect its receipt.')
    filename,status,e1=PHASES[phase]
    if phase=='release_squid' and (FOLDER/'squid_continue_delivery.json').exists():
        filename='squid_continue_delivery.json'
    if phase=='release_squid' and (FOLDER/'squid_deliver_after_clearance_stop.json').exists():
        filename='squid_deliver_after_clearance_stop.json'
    if phase=='release_squid' and (FOLDER/'squid_deliver_after_connector_check.json').exists():
        filename='squid_deliver_after_connector_check.json'
    source=FOLDER/filename;data=json.loads(source.read_bytes())
    if data.get('status')!=status:raise TransferError('Completed preceding phase required.')
    if phase=='continue_delivery':
        failed=FOLDER/'squid_deliver.json'
        opening=FOLDER/data['opening_file']
        if opening.parent!=FOLDER or not opening.name.startswith('authorized_open_'):
            raise TransferError('Reviewed opening receipt required.')
        old=json.loads(failed.read_bytes());released=json.loads(opening.read_bytes())
        if (data.get('operator_requested_continuation') is not True
                or data.get('failed_sha256')!=digest(failed)
                or data.get('opening_sha256')!=digest(opening)
                or old.get('status')!='failed_or_uncertain'
                or old.get('error')!='Uncertain grip/opening; no retry or lift.'
                or released.get('status')!='opened_verified'
                or released.get('target_e1')!=28
                or data.get('final')!=released.get('after',{}).get('robot')):
            raise TransferError('Continuation must bind the reviewed failure and verified release.')
    if phase in ('deliver_after_clearance_stop','deliver_after_connector_check'):
        connector=phase=='deliver_after_connector_check'
        failed=FOLDER/('squid_deliver_after_clearance_stop.json' if connector else 'squid_continue_delivery.json')
        old=json.loads(failed.read_bytes())
        if (data.get('operator_confirmed_plate_in_holder_jaws_empty') is not True
                or data.get('failed_sha256')!=digest(failed)
                or old.get('status')!='failed_or_uncertain'
                or old.get('error')!=('Queued path segment exceeds the reviewed step size.' if connector else 'Squid vertical motion exceeded reviewed height')
                or data.get('native',{}).get('external_axes',{}).get('E1',0)<27.93):
            raise TransferError('Reviewed clearance stop and operator-confirmed empty-arm preparation required.')
    acceptance=None
    if phase in ('release_squid','release_home'):
        acceptance_path=FOLDER/('squid_seating_acceptance.json' if phase=='release_squid' else 'squid_HOME_return_acceptance.json')
        acceptance=json.loads(acceptance_path.read_bytes())
        if acceptance.get('accepted') is not True or acceptance.get('source_sha256')!=digest(source):
            raise TransferError('Operator support acceptance must match this arrival.')
    g=geometry();s=preflight(service);n=native(service)
    if n['moving'] or not all(math.isfinite(n['external_axes'][k]) for k in ('E1','E2')) or abs(n['external_axes']['E1']-e1)>.1:
        raise TransferError('Unexpected jaw or motion state.')
    angle=n['external_axes']['E2']
    if (abs(angle-90.71661229181757)>.5 if phase=='deliver' else
            abs(angle-1.77)>.5 if phase in ('continue_delivery','deliver_after_clearance_stop','deliver_after_connector_check') else not accepted(angle)):
        raise TransferError('Unexpected HOME holder orientation.')
    near(s['pose_mm'],data['final']['pose_mm'],.05)
    expected=(g['expected_start'] if phase=='deliver' else g['seat'] if phase=='continue_delivery'
              else g['points'][0] if phase in ('deliver_after_clearance_stop','deliver_after_connector_check') else g['clearance'] if phase=='retrieve'
              else g['seat'] if phase=='release_home' else g['points'][-1])
    near(s['pose_mm'],expected,.05)
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
        raise TransferError('Cellvis route configuration changed.')
    q=s['joints']
    if phase in ('deliver','continue_delivery','deliver_after_clearance_stop','deliver_after_connector_check'):
        if abs(angle-1.77)>90.01:raise TransferError('Holder rotation exceeds its published segment limit.')
        from trajectory_queue import prepare_points
        # Exercise the executor's segment classification before holder motion,
        # including high-clearance recovery starts, not just the IK solver.
        prepare_points(s['pose_mm'],q,[g['clearance']],cfg,reviewed=True,vertical_runs=True)
        q=checked(s['pose_mm'],[g['clearance'],g['seat'],g['proof']],q,cfg,service.envelope)
        q=check_route(g['proof'],g['points'],q,cfg,service.envelope)
    elif phase=='retrieve':
        q=checked(s['pose_mm'],[g['proof']],q,cfg,service.envelope)
        q=check_route(g['proof'],g['points'],q,cfg,service.envelope)
    if phase in ('deliver','continue_delivery','deliver_after_clearance_stop','deliver_after_connector_check','retrieve','empty_return'):
        q=check_route(g['points'][-1],g['reverse'],q,cfg,service.envelope)
        checked(g['proof'],[g['seat'] if phase=='retrieve' else g['clearance']],q,cfg,service.envelope)
    if phase=='release_home':checked(s['pose_mm'],[g['clearance']],q,cfg,service.envelope)
    from trajectory_queue import LuaTrajectory
    cap=LuaTrajectory(service).capability()
    if not cap.get('available') or cap.get('version')!=220109:raise TransferError('Mixed-speed Lua queue220109 required.')
    return dict(phase=phase,source=str(source),source_sha256=digest(source),route_sha256=PLAN_SHA,
                start=s['pose_mm'],joints=s['joints'],e1=e1,e2=angle,acceptance=acceptance,
                squid_position=instrument_ready(g))


def execute(run,service,cfg,approved):
    fresh=plan(service,cfg,approved['phase']);g=geometry();phase=fresh['phase']
    for key in ('phase','source','source_sha256','route_sha256','e1','acceptance'):
        if fresh[key]!=approved.get(key):raise TransferError('Cellvis Squid plan changed.')
    near(fresh['start'],approved['start'],.05)
    if abs(fresh['e2']-approved['e2'])>.05 or any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Starting configuration changed.')
    path=FOLDER/('squid_'+phase+'.json');expected_e1=fresh['e1'];holder_angle=fresh['e2']
    record=dict(status='started',plan=fresh,steps=[],samples=[],motion_sent=False)
    with path.open('x') as stream:json.dump(record,stream,indent=2)
    def save():write_run_record(path,record)
    def check(stationary=False,holder=False,jaws=True):
        s=preflight(service);n=native(service);axes=n['external_axes']
        if run.stopped() or (stationary and n['moving']):raise TransferError('Stopped or motion unsettled.')
        if not all(math.isfinite(axes[k]) for k in ('E1','E2')):raise TransferError('Invalid external-axis feedback.')
        if jaws and abs(axes['E1']-expected_e1)>.1:raise TransferError('Unexpected jaw position.')
        if holder and (not accepted(axes['E2']) if holder_angle==1.77 else abs(axes['E2']-holder_angle)>.5):
            raise TransferError('HOME holder changed before approach.')
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=axes));save()
        return s,n
    def queue(label,points,speed,holder=False,**flags):
        s,_=check(True,holder);run.say(label)
        step=dict(label=label,points=points,speed=speed,status='dispatching');record['steps'].append(step)
        record['motion_sent']=True;save()
        from trajectory_queue import LuaTrajectory
        result=LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],points,cfg,speed,
            lambda *args:check(holder=holder),reviewed=True,**flags)
        if not result.get('ok') or result.get('recovered'):raise TransferError('Uncertain Cellvis queue; no retry.')
        s,_=check(True,holder);near(s['pose_mm'],points[-1],.1)
        step.update(status='completed',response=result);save()
    def jaws(target,speed,pose,holder=False):
        nonlocal expected_e1
        before,_=check(True,holder);near(before['pose_mm'],pose,.05)
        step=dict(label='Cellvis jaws',target=target,speed=speed,status='dispatching');record['steps'].append(step)
        record['motion_sent']=True;save()
        result=service.move_gripper(target,speed);step['response']=result;save()
        # Match ReferenceGrip: the immediate report may precede settling.
        # Record its contact hint, then require settled native feedback and
        # a fresh stationary torque/position report before any lift.
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
            raise TransferError('Uncertain grip/opening; no retry or lift.')
        deadline=time.monotonic()+2;stable=0
        while stable<3:
            s,n=check(True,holder,False);near(s['pose_mm'],before['pose_mm'],.05)
            stable=stable+1 if abs(n['external_axes']['E1']-target)<=.07 else 0
            if time.monotonic()>deadline:raise TransferError('Jaw arrival not verified.')
            if stable<3:time.sleep(.1)
        expected_e1=target
        torque=service.torque_report()
        if not torque.get('ok') or not torque.get('telemetry_live') or not math.isfinite(torque['e1_torque']) or abs(torque['e1_position']-target)>.07:
            raise TransferError('Fresh gripper feedback unavailable.')
        step.update(status='completed',torque_report=torque);save()
    def observe_grip(pose,holder=False):
        for _ in range(20):
            s,_=check(True,holder);near(s['pose_mm'],pose,.05);time.sleep(.1)
    try:
        check(True,True);instrument_ready(g)
        if phase in ('deliver','continue_delivery','deliver_after_clearance_stop','deliver_after_connector_check'):
            if phase=='continue_delivery':
                queue('Raise released open jaws 30 mm before holder correction',
                      [dict(fresh['start'],Z=g['clearance']['Z'])],5,holder=True,home_transit=True)
            run.say('Restore released HOME holder to 1.77 degrees for Cellvis long-side pickup.')
            def rotate():
                before,_=check(True,True);token=secrets.randbelow(1000000)+1
                probe=service._hostpoint({7:float(token)},13,5)
                if not probe.get('ok') or probe.get('recovered') or service.robot.get_sys_var_i([7,8])!={7:token,8:250104}:
                    raise TransferError('Holder interface unavailable.')
                check(True,True);record['motion_sent']=True;save()
                result=service._hostpoint({7:float(token),8:fresh['e2'],9:1.77},14,120)
                if not result.get('ok') or result.get('recovered'):raise TransferError('Holder rotation uncertain; no retry.')
                near(service.pose_mm(),before['pose_mm'],.05)
                return result
            record['rotation']=service._locked(rotate)
            if not record['rotation'].get('ok'):raise TransferError('Holder rotation failed.')
            holder_angle=1.77
            for _ in range(3):check(True,True);time.sleep(.1)
            queue('Connect above accepted Cellvis long-side pickup',[g['clearance']],5,holder=True,vertical_runs=True)
            queue('First 10 mm descent',[dict(g['seat'],Z=g['seat']['Z']+20)],137,holder=True,home_transit=True,home_speed137=True)
            queue('Final 20 mm descent',[g['seat']],5,holder=True,home_transit=True)
            for command in closure_commands(28,3.9):jaws(command['target_e1_mm'],command['speed'],g['seat'],True)
            observe_grip(g['seat'],True)
            queue('Cellvis proof lift 5 mm slowly',[g['proof']],5,holder=True,home_transit=True)
            instrument_ready(g)
            queue('One Lua queue HOME to Squid; slow final seating',g['points'],137,
                  squid_queue='cellvis24_home_holder',segment_speeds=g['speeds'])
        elif phase=='release_squid':
            jaws(7,5,g['points'][-1])
        elif phase=='empty_return':
            queue('Empty Squid departure and HOME return',g['reverse'],137,
                  squid_queue='cellvis24_home_holder',segment_speeds=g['reverse_speeds'])
            queue('Empty arm to HOME clearance',[g['clearance']],137,holder=True,home_transit=True,home_speed137=True)
        elif phase=='retrieve':
            queue('Empty connector to Squid route',[g['proof']],5,holder=True,home_transit=True)
            instrument_ready(g)
            queue('Empty approach to Cellvis at Squid',g['points'],137,
                  squid_queue='cellvis24_home_holder',segment_speeds=g['speeds'])
            for command in closure_commands(7,3.9):jaws(command['target_e1_mm'],command['speed'],g['points'][-1])
            observe_grip(g['points'][-1])
            queue('Loaded Squid departure and HOME return',g['reverse'],137,
                  squid_queue='cellvis24_home_holder',segment_speeds=g['reverse_speeds'])
            queue('Reseat Cellvis in HOME; stop held',[g['seat']],5,holder=True,home_transit=True)
        else:
            jaws(28,5,g['seat'],True)
            queue('Empty HOME clearance',[g['clearance']],137,holder=True,home_transit=True,home_speed137=True)
        s,n=check(True);record.update(status='completed',final=s,final_native=n,
            payload='held' if phase in ('deliver','continue_delivery','deliver_after_clearance_stop','deliver_after_connector_check','retrieve') else 'empty',
            support_inspection_required=phase in ('deliver','continue_delivery','deliver_after_clearance_stop','deliver_after_connector_check','retrieve'))
        return dict(ok=True,record=str(path),pose_mm=s['pose_mm'],payload=record['payload'],support_inspection_required=record['support_inspection_required'])
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error))
        if record['motion_sent']:
            try:record['stop_response']=service.program('stop')
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:record['finished_at']=time.time();save()
