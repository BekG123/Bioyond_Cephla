"""Reviewed HOME long-side pickup and direct Squid approach; stop held."""
from copy import deepcopy
import json
import math
import secrets
import time
from pathlib import Path
from uuid import uuid4
from autonomy import TransferError,check_path
from scope_step_trial import preflight,near
from calibration_e2 import accepted,TARGET_DEGREES
import home_hamilton_exchange as exchange
from squid_single_queue import route,quantize
from squid_handling_route import CURRENT_SHA
from trajectory_queue import LuaTrajectory
from projected_pickup import load,accepted_grip
from gripper_closure import POLICY
from home_seating import seating_plan

FOLDER=exchange.ROOT/'operator_ui/reports/plate_session/home_squid'


def geometry():
    profile,digest=load()
    if digest!=exchange.PROFILE_SHA or not accepted_grip(profile):raise TransferError('Accepted long-side pickup changed.')
    parent,path,_=route('forward')
    seat=quantize(profile['candidate_endpoint']);proof=dict(seat,Z=round(seat['Z']+5,2))
    clearance=dict(seat,Z=round(seat['Z']+30,2))
    points=[dict(proof,Z=291.24)]+[quantize(p) for p in path[2:]]
    return dict(profile=profile,profile_sha256=digest,squid_sha256=CURRENT_SHA,cfg=parent['cfg'],
        envelope=parent['envelope'],seat=seat,proof=proof,clearance=clearance,points=points,speeds=[137,137,137,5])


def validate_route(start,points):
    g=geometry()
    candidates=[(g['proof'],g['points'],g['speeds']),
                (g['points'][-1],list(reversed([g['proof']]+g['points'][:-1])),[5,137,137,137])]
    for origin,targets,speeds in candidates:
        try:near(start,origin,.05)
        except TransferError:continue
        if [quantize(p) for p in points]==targets:return g,speeds
    raise TransferError('Exact reviewed HOME/Squid path required.')


def checked(start,points,joints,cfg,envelope):
    q=deepcopy(joints);offset=q['J1']-start['Z'];previous=start
    for point in points:
        q=check_path(previous,point,q,cfg,envelope);q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('HOME/Squid joint travel exceeded.')
        previous=point
    return q


def check_route(start,points,joints,cfg,envelope):
    g,_=validate_route(start,points)
    if cfg!=g['cfg'] or {k:list(v) for k,v in envelope.items()}!=g['envelope']:
        raise TransferError('HOME/Squid configuration changed.')
    return checked(start,points,joints,cfg,envelope)


def plan(service,cfg,source):
    from hamilton_holder_dropoff import FOLDER as source_folder,STATUSES
    source=Path(source).resolve()
    data=json.loads(source.read_bytes())
    g=geometry();binding={};rotate_holder=True
    if data.get('status')=='calibration_completed_at_HOME':
        data,binding=exchange.calibration_evidence(source)
        rotate_holder=False
    elif source.parent==source_folder.resolve() and data.get('status')==STATUSES['finish_home']:
        if not 0<=time.time()-data['finished_at']<=1800:
            raise TransferError('Fresh completed HOME release/clearance receipt required.')
    elif source.parent==FOLDER.resolve() and data.get('status')=='plate_released_at_HOME_clearance':
        if not 0<=time.time()-data['finished_at']<=1800 or data['plan']['geometry']!=g:
            raise TransferError('Fresh unchanged HOME clearance receipt required.')
        rotate_holder=False
    else:raise TransferError('Unexpected or incomplete HOME receipt.')
    for p in FOLDER.glob('*.json'):
        if json.loads(p.read_bytes()).get('plan',{}).get('source')==str(source):
            raise TransferError('This HOME/Squid trial was already attempted; no automatic retry.')
    s=preflight(service);n=exchange.native(service)
    if n['moving'] or not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-28)>.15:
        raise TransferError('Stationary released jaws28 required.')
    near(s['pose_mm'],data['final']['pose_mm'],.05)
    _,_,short=exchange.reference('04')
    expected_start=dict(short['descent_endpoint'],Z=short['descent_endpoint']['Z']+30) if rotate_holder else g['clearance']
    near(s['pose_mm'],expected_start,.1)
    angle=n['external_axes']['E2']
    if not math.isfinite(angle) or (abs(angle-short['holder_e2_degrees'])>.5 if rotate_holder else not accepted(angle)):
        raise TransferError('Unexpected starting holder orientation.')
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
        raise TransferError('Pickup/route configuration changed.')
    q=checked(s['pose_mm'],[g['clearance'],g['seat'],g['proof']],s['joints'],cfg,service.envelope)
    end=check_route(g['proof'],g['points'],q,cfg,service.envelope)
    checked(g['points'][-1],list(reversed([g['proof']]+g['points'][:-1])),end,cfg,service.envelope)
    cap=LuaTrajectory(service).capability()
    if not cap.get('available') or cap.get('version')!=220109:raise TransferError('Mixed-speed Lua queue220109 required.')
    return dict(id=uuid4().hex,source=str(source),source_sha256=exchange.digest(source),start=s['pose_mm'],joints=s['joints'],
        closure_policy=POLICY,e2=angle,geometry=g,rotation_target=TARGET_DEGREES,rotate_holder=rotate_holder,
        calibration_binding=binding,holder_acceptance=[1.750,1.82],release_at_squid=False,idle_travel=False)


def execute(run,service,cfg,approved,gripper):
    fresh=plan(service,cfg,approved['source'])
    for key in ('source','source_sha256','geometry','rotation_target','rotate_holder','calibration_binding','holder_acceptance','release_at_squid','idle_travel','closure_policy'):
        if approved.get(key)!=fresh[key]:raise TransferError('HOME/Squid plan changed: '+key)
    near(fresh['start'],approved['start'],.05)
    if abs(fresh['e2']-approved['e2'])>.05 or any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Starting configuration moved after preview.')
    ident=approved.get('id','')
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise TransferError('Invalid trial id.')
    FOLDER.mkdir(parents=True,exist_ok=True);path=FOLDER/(ident+'.json')
    record=dict(status='started',at=time.time(),plan=approved,phases=[],samples=[],release_at_squid=False)
    with path.open('x') as stream:json.dump(record,stream,indent=2)
    def save():path.write_text(json.dumps(record,indent=2))
    g=fresh['geometry'];expected_e1=28;holder_required=False
    def check(stationary=False):
        if run.stopped():raise TransferError('HOME/Squid stopped.')
        s=preflight(service);n=exchange.native(service)
        if stationary and n['moving']:raise TransferError('Motion not settled.')
        if not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-expected_e1)>.1:
            raise TransferError('Grip feedback changed unexpectedly.')
        if holder_required and not accepted(n['external_axes']['E2']):raise TransferError('Original holder angle changed before pickup.')
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
        return s
    def queue(label,points,speed,**flags):
        s=check(True);run.say(label)
        item=dict(label=label,points=points,speed=speed,status='dispatching');record['phases'].append(item);save()
        result=LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],points,cfg,speed,lambda *args:check(),reviewed=True,**flags)
        if not result.get('ok') or result.get('recovered'):raise TransferError(label+' uncertain; no retry.')
        after=check(True);near(after['pose_mm'],points[-1],.1)
        item.update(status='completed',result=result);save()
    try:
        before=check(True);run.say('Restore released HOME holder to1.77 degrees.')
        def rotate():
            check(True);n=exchange.native(service)
            if abs(n['external_axes']['E2']-fresh['e2'])>.05:raise TransferError('Holder changed before rotation.')
            if abs(fresh['e2']-TARGET_DEGREES)>90.01:raise TransferError('Rotation exceeds published segment limit.')
            token=secrets.randbelow(1000000)+1
            probe=service._hostpoint({7:float(token)},13,5)
            regs=service.robot.get_sys_var_i([7,8])
            if not probe.get('ok') or regs.get(7)!=token or regs.get(8)!=250104:raise TransferError('Holder interface mismatch.')
            if run.stopped():raise TransferError('Stopped before rotation.')
            record['rotation_dispatched']=True;save()
            result=service._hostpoint({7:float(token),8:fresh['e2'],9:TARGET_DEGREES},14,120)
            if not result.get('ok') or result.get('recovered'):raise TransferError('Holder rotation uncertain; no retry.')
            near(service.pose_mm(),before['pose_mm'],.05)
            return result
        if fresh['rotate_holder']:
            record['rotation_result']=service._locked(rotate)
            if not record['rotation_result'].get('ok'):raise TransferError('Holder rotation failed.')
        else:record['rotation_result']=dict(ok=True,motion_sent=False,reason='Original holder verified; no rotation needed.')
        holder_required=True
        for _ in range(3):check(True);time.sleep(.1)
        if fresh['rotate_holder']:queue('Connect to accepted long-side clearance',[g['clearance']],5)
        queue('First10mm descent',[dict(g['seat'],Z=g['seat']['Z']+20)],137,home_transit=True,home_speed137=True)
        queue('Final20mm descent',[g['seat']],5,home_transit=True)
        s=check(True)
        context=dict(plate_profile_id=g['profile']['id'],descent_correction=dict(endpoint=g['profile']['candidate_endpoint'],profile_sha256=g['profile_sha256']))
        reference,digest=gripper._configuration(context)
        receipt=dict(pose_mm=s['pose_mm'],descent_result=context,grip_reference_sha256=digest,home_squid_trial=str(path))
        record['descent_receipt']=receipt;save();run.say('Use accepted long-side grip3.9.')
        result=gripper.execute(run,receipt);record['grip_result']=result;save()
        if not result.get('ok') or result.get('recovered'):raise TransferError('Long-side grip uncertain; no lift.')
        expected_e1=3.9;check(True);holder_required=False
        queue('Proof lift5 at speed5',[g['proof']],5,home_transit=True)
        queue('Direct HOME to Squid; stop held',g['points'],137,squid_queue='home_holder',segment_speeds=g['speeds'])
        s=check(True);record.update(status='at_squid_held_pending_operator_assessment',final=s)
        return dict(ok=True,status=record['status'],record=str(path),pose_mm=s['pose_mm'],payload='held_pending_inspection')
    except Exception as error:record.update(status='failed_or_uncertain',error=str(error));raise
    finally:record['finished_at']=time.time();save();run.audit('home_squid_transfer',record=str(path))


def plan_return(service,cfg,source,phase='return'):
    if phase not in ('return','release_home'):raise TransferError('Unknown HOME/Squid return phase.')
    source=Path(source).resolve()
    if source.parent!=FOLDER.resolve():raise TransferError('Unexpected source receipt.')
    data=json.loads(source.read_bytes())
    expected='at_squid_held_pending_operator_assessment' if phase=='return' else 'returned_held_at_HOME_seat'
    if data.get('status')!=expected or not 0<=time.time()-data['finished_at']<=1800:
        raise TransferError('Fresh completed predecessor required.')
    for p in FOLDER.glob('*.json'):
        prior=json.loads(p.read_bytes()).get('plan',{})
        if prior.get('source')==str(source):raise TransferError('Return phase already attempted; inspect, no retry.')
    g=geometry()
    if data['plan']['geometry']!=g:raise TransferError('Bound pickup/Squid geometry changed.')
    seating=seating_plan(g['seat'])
    if phase=='release_home' and data['plan'].get('home_seating')!=seating:
        raise TransferError('A fresh return to the continuous HOME seating endpoint is required.')
    s=preflight(service);n=exchange.native(service)
    if n['moving'] or not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-3.9)>.1:
        raise TransferError('Stationary accepted grip3.9 required.')
    if not accepted(n['external_axes']['E2']):raise TransferError('HOME holder is not in its accepted original orientation.')
    near(s['pose_mm'],data['final']['pose_mm'],.05)
    near(s['pose_mm'],g['points'][-1] if phase=='return' else seating['pose'],.05)
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
        raise TransferError('Return configuration changed.')
    reverse=list(reversed([g['proof']]+g['points'][:-1]));q=s['joints']
    if phase=='return':
        q=check_route(s['pose_mm'],reverse,q,cfg,service.envelope)
        q=checked(g['proof'],[seating['pose']],q,cfg,service.envelope)
    checked(seating['pose'],[g['clearance']],q,cfg,service.envelope)
    return dict(id=uuid4().hex,phase=phase,source=str(source),source_sha256=exchange.digest(source),
        geometry=g,start=s['pose_mm'],joints=s['joints'],e2=n['external_axes']['E2'],points=reverse,speeds=[5,137,137,137],home_seating=seating)


def execute_return(run,service,cfg,approved):
    fresh=plan_return(service,cfg,approved['source'],approved['phase'])
    for key in ('phase','source','source_sha256','geometry','points','speeds','home_seating'):
        if approved.get(key)!=fresh[key]:raise TransferError('Return plan changed: '+key)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):raise TransferError('Return starting joints changed.')
    ident=approved.get('id','')
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise TransferError('Invalid trial id.')
    path=FOLDER/(ident+'.json');record=dict(status='started',at=time.time(),plan=approved,phases=[],samples=[])
    with path.open('x') as stream:json.dump(record,stream,indent=2)
    def save():path.write_text(json.dumps(record,indent=2))
    expected_e1=3.9;g=fresh['geometry']
    def check(stationary=False,holder=False):
        if run.stopped():raise TransferError('Return stopped.')
        s=preflight(service);n=exchange.native(service)
        if stationary and n['moving']:raise TransferError('Return not stationary.')
        if not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-expected_e1)>.1:raise TransferError('Return grip changed.')
        if holder and not accepted(n['external_axes']['E2']):raise TransferError('Holder changed before HOME seating.')
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save();return s
    def queue(label,points,speed,holder=False,**flags):
        s=check(True,holder);run.say(label)
        item=dict(label=label,points=points,speed=speed,status='dispatching');record['phases'].append(item);save()
        result=LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],points,cfg,speed,lambda *args:check(holder=holder),reviewed=True,**flags)
        if not result.get('ok') or result.get('recovered'):raise TransferError('Return motion uncertain; no retry.')
        s=check(True,holder);near(s['pose_mm'],points[-1],.1);item.update(status='completed',result=result);save()
    try:
        check(True,True)
        if fresh['phase']=='return':
            queue('Slow Squid departure and direct HOME return',fresh['points'],137,squid_queue='home_holder',segment_speeds=fresh['speeds'])
            seating=fresh['home_seating']
            queue('Continuous HOME seating descent',[seating['pose']],seating['speed'],holder=True,home_transit=True)
            status='returned_held_at_HOME_seat'
        else:
            before=check(True,True);run.say('Release supported plate at HOME to28.')
            record['release_dispatched']=True;save()
            result=service.move_gripper(28,5);record['release_result']=result;save()
            if not result.get('ok') or result.get('recovered'):raise TransferError('HOME release uncertain; no retry.')
            expected_e1=28;s=check(True,True);near(s['pose_mm'],before['pose_mm'],.05)
            queue('Return empty to HOME clearance',[g['clearance']],137,holder=True,home_transit=True,home_speed137=True)
            status='plate_released_at_HOME_clearance'
        s=check(True,True);record.update(status=status,final=s)
        return dict(ok=True,status=status,record=str(path),pose_mm=s['pose_mm'],payload='held' if fresh['phase']=='return' else 'empty')
    except Exception as error:record.update(status='failed_or_uncertain',error=str(error));raise
    finally:record['finished_at']=time.time();save();run.audit('home_squid_return',record=str(path))
