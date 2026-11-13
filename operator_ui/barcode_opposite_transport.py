"""Receipt-bound opposite-side scanner travel; no holder or gripper commands."""
import json
import secrets
import time
from pathlib import Path
from uuid import uuid4
from barcode_opposite_pickup import source_data
from barcode_opposite_side_trial import TARGET as HOLDER_TARGET,OUTPUT
from cellvis24_scanner_return import sha
from cellvis24_scanner_route import checked_geometry
from scanner_empty_route import TARGET,TRIAL,ORIGINAL
from scope_compact137 import HoldingService
from scope_step_trial import preflight,near
from home_hamilton_exchange import native
from home_hamilton_exchange import holder_restore_targets
from calibration_e2 import accepted
from holder_contact_monitor import holder_ok
from gripper_closure import grip_feedback_matches
from home_squid_transfer import checked
from autonomy import TransferError
from trajectory_queue import LuaTrajectory,prepare_points,travel_program_blocker
from run_record_io import write_run_record


LOWER_SCANNER_Z=163.76  # Requested one-inch reduction; old receipts retain189.16.


def binding(source,phase,require_fresh=True,scanner_z=None):
    if scanner_z is not None and (phase!='scanner' or scanner_z not in (TARGET['Z'],LOWER_SCANNER_Z)):
        raise TransferError('Select the nominal or reviewed one-inch-lower scanner target only.')
    scanner_target=dict(TARGET,Z=TARGET['Z'] if scanner_z is None else scanner_z)
    source=Path(source).resolve()
    if source.parent.parent!=OUTPUT.resolve() or source.name not in ('pickup.json','pickup_after_load.json'):
        raise TransferError('Opposite-side pickup receipt required.')
    d=json.loads(source.read_bytes());trial,_,g=source_data(d['source'],require_fresh=False)
    if d.get('status')!='proof_lift_completed_retention_pending' or d['source_sha256']!=sha(trial) or d['geometry']!=g:
        raise TransferError('Matching completed opposite-side lift required.')
    latest=d
    if d['holder_target'] not in (1.77,HOLDER_TARGET) or d['grip_target']!=3.9 or d['lift_speed']!=5:
        raise TransferError('Pickup settings changed.')
    proof=dict(g['seat'],Z=g['seat']['Z']+5)
    near(d['final']['robot']['pose_mm'],proof,.05)
    sources={str(source):sha(source),str(trial):sha(trial)}
    if phase=='scanner':
        start=proof;points=[dict(proof,Z=300.),dict(scanner_target,Z=300.),scanner_target]
    elif phase=='return_home':
        previous=source.with_name('scanner.json');p=json.loads(previous.read_bytes())
        scanner_target=p['plan']['binding'].get('scanner_target',dict(TARGET))
        if scanner_target!=dict(TARGET,Z=scanner_target['Z']):raise TransferError('Scanner XY/wrist target changed.')
        if p['status']!='at_scanner_held' or p['plan']['binding']!=binding(source,'scanner',require_fresh=False,scanner_z=scanner_target['Z']):
            raise TransferError('Completed matching scanner transfer required.')
        if not p.get('envelope_restoration',{}).get('ok'):raise TransferError('Scanner workspace not restored.')
        sources[str(previous)]=sha(previous)
        latest=p
        start=scanner_target;points=[dict(scanner_target,Z=300.),dict(proof,Z=300.),proof]
    elif phase=='release_restore':
        previous=source.with_name('return_home.json');p=json.loads(previous.read_bytes())
        if p['status']!='at_HOME_held' or p['plan']['binding']!=binding(source,'return_home',require_fresh=False):
            raise TransferError('Completed matching HOME seating required.')
        if not p.get('envelope_restoration',{}).get('ok'):raise TransferError('Return workspace not restored.')
        sources[str(previous)]=sha(previous)
        latest=p
        start=g['seat'];points=[g['clearance'],g['station_clearance']]
    else:raise TransferError('Unknown opposite-side transport phase.')
    if require_fresh and not 0<=time.time()-latest['finished_at']<=1800:
        raise TransferError('Latest completed phase evidence expired.')
    result=dict(source=str(source),phase=phase,start=start,points=points,seat=g['seat'],
        clearance=g['clearance'],station_clearance=g['station_clearance'],cfg=g['cfg'],sources=sources)
    # Preserve previously issued 180-degree receipt bindings exactly.
    if d['holder_target']==1.77:result['holder_target']=1.77
    if phase in ('scanner','return_home') and scanner_target['Z']!=TARGET['Z']:
        result['scanner_target']=scanner_target
    return result


class OppositeHoldingService(HoldingService):
    def __init__(self,service,g):
        super().__init__(service,3.9,{k:list(v) for k,v in TRIAL.items()});self.binding=g


def prepare_for_service(service,start,joints,points,cfg,envelope):
    if not isinstance(service,OppositeHoldingService):raise TransferError('Bound opposite-side service required.')
    refusal=service._preflight()
    if refusal:raise TransferError(refusal)
    g=binding(service.binding['source'],service.binding['phase'],
        scanner_z=service.binding.get('scanner_target',{}).get('Z') if service.binding['phase']=='scanner' else None)
    if g!=service.binding:raise TransferError('Opposite-side scanner evidence changed.')
    return checked_geometry(g,start,joints,points,cfg,envelope)


def plan(service,cfg,source,phase,scanner_z=None):
    g=binding(source,phase,scanner_z=scanner_z);s=preflight(service);n=native(service)
    if (n['moving'] or not service.envelope_enabled or
        {k:tuple(v) for k,v in service.envelope.items()}!=ORIGINAL or
        not grip_feedback_matches(n['external_axes']['E1'],3.9) or
        not holder_ok(n['external_axes']['E2'],g.get('holder_target',HOLDER_TARGET),True)):
        raise TransferError('Stationary held plate, original workspace and rotated holder required.')
    if Path(source).with_name(phase+'.json').exists():raise TransferError('Phase already attempted; no retry.')
    if cfg!=g['cfg']:raise TransferError('Configuration changed.')
    near(s['pose_mm'],g['start'],.05)
    if phase=='release_restore':
        q=checked(s['pose_mm'],g['points'],s['joints'],cfg,ORIGINAL)
        prepare_points(s['pose_mm'],s['joints'],[g['clearance']],cfg,reviewed=True,home_transit=True)
        prepare_points(g['clearance'],q,[g['station_clearance']],cfg,reviewed=True)
    else:_,q=checked_geometry(g,s['pose_mm'],s['joints'],g['points'],cfg,TRIAL)
    if phase=='return_home':
        checked(g['points'][-1],[g['seat']],q,cfg,TRIAL)
        prepare_points(g['points'][-1],q,[g['seat']],cfg,reviewed=True,home_transit=True)
    blocker=travel_program_blocker(LuaTrajectory(service).capability(),137)
    if blocker:raise TransferError(blocker)
    return dict(id=uuid4().hex,at=time.time(),binding=g,start=s['pose_mm'],joints=s['joints'],
        implementation={str(p):sha(p) for p in (Path(__file__),Path(__file__).with_name('trajectory_queue.py'))})


def execute(run,service,cfg,approved):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Preview expired.')
    old=approved['binding'];fresh=plan(service,cfg,old['source'],old['phase'],
        scanner_z=old.get('scanner_target',{}).get('Z') if old['phase']=='scanner' else None)
    for k in ('binding','implementation'):
        if fresh[k]!=approved[k]:raise TransferError('Transport changed: '+k)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Joint start changed.')
    g=fresh['binding'];path=Path(g['source']).with_name(g['phase']+'.json')
    r=dict(status='checking',plan=approved,steps=[],samples=[],motion_sent=False,payload='held',
        retention_confirmed=True,route_clear_confirmed=True,automatic_retries=False)
    with path.open('x') as f:json.dump(r,f)
    def save():write_run_record(path,r)
    def require(v):
        if not v.get('ok') or v.get('recovered'):raise TransferError('Uncertain command; no retry: '+str(v))
        return v
    owner=OppositeHoldingService(service,g);changed=False;expected_e1=3.9;expected_holder=g.get('holder_target',HOLDER_TARGET)
    def monitor(*args):
        s=preflight(service);n=native(service)
        jaw_ok=(abs(n['external_axes']['E1']-28)<=.07 if expected_e1==28 else grip_feedback_matches(n['external_axes']['E1'],expected_e1))
        if run.stopped() or not jaw_ok or not holder_ok(n['external_axes']['E2'],expected_holder,True):
            raise TransferError('Stopped or rotated holder feedback changed.')
        r['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
    try:
        if run.stopped():raise TransferError('Stopped before dispatch.')
        if g['phase']=='release_restore':
            monitor();near(service.pose_mm(),g['seat'],.05)
            r['motion_sent']=True;save()
            r['opening']=require(service.move_gripper(28,5));save()
            deadline=time.monotonic()+2;stable=0
            while stable<3:
                n=native(service);preflight(service);near(service.pose_mm(),g['seat'],.05)
                if run.stopped():raise TransferError('Stopped during release.')
                stable=stable+1 if abs(n['external_axes']['E1']-28)<=.07 else 0
                if time.monotonic()>deadline:raise TransferError('Release not confirmed; no lift or rotation.')
                if stable<3:time.sleep(.1)
            expected_e1=28;monitor()
            s=preflight(service)
            r['steps'].append(dict(kind='released_clearance',result=require(LuaTrajectory(service).execute(run,
                s['pose_mm'],s['joints'],[g['clearance']],cfg,137,monitor,reviewed=True,home_transit=True,home_speed137=True))))
            save();monitor()
            for target in holder_restore_targets(native(service)['external_axes']['E2'],1.77):
                def rotate():
                    monitor();near(service.pose_mm(),g['clearance'],.05)
                    n=native(service);origin=n['external_axes']['E2']
                    if n['moving'] or abs(target-origin)>90.01 or abs(target)>360:raise TransferError('Holder rotation bounds exceeded.')
                    token=secrets.randbelow(1000000)+1
                    require(service._hostpoint({7:float(token)},13,5))
                    if service.robot.get_sys_var_i([7,8])!={7:token,8:250104}:raise TransferError('Holder interface mismatch.')
                    monitor()
                    return service._hostpoint({7:float(token),8:origin,9:target},14,120)
                run.say(f'Restore released holder to {target:.3f} degrees.')
                result=require(service._locked(rotate));expected_holder=target;monitor()
                r['steps'].append(dict(kind='holder_restore',target=target,result=result));save()
            for _ in range(3):
                monitor()
                if not accepted(native(service)['external_axes']['E2']):raise TransferError('Original holder angle not verified; no station pickup.')
                time.sleep(.1)
            s=preflight(service)
            r['steps'].append(dict(kind='station_clearance',result=require(LuaTrajectory(service).execute(run,
                s['pose_mm'],s['joints'],[g['station_clearance']],cfg,5,monitor,reviewed=True))))
            monitor();s=preflight(service);near(s['pose_mm'],g['station_clearance'],.05)
            r.update(status='completed',payload='empty',final=s,final_native=native(service),support_confirmed=True)
            return dict(ok=True,record=str(path),status=r['status'],pose_mm=s['pose_mm'])
        changed=True;require(service.set_envelope(*(v for k in ('X','Y','Z') for v in TRIAL[k])))
        monitor();r['motion_sent']=True;save()
        run.say('Opposite barcode '+g['phase']+': one scanner queue at137.')
        result=require(LuaTrajectory(owner).execute(run,fresh['start'],fresh['joints'],g['points'],cfg,137,
            monitor,reviewed=True,scanner_loaded='cellvis_opposite'))
        r['steps'].append(dict(kind='scanner_queue',result=result));save();monitor()
        if g['phase']=='return_home':
            s=preflight(owner)
            run.say('Seat rotated plate in HOME at5; keep jaws closed.')
            result=require(LuaTrajectory(owner).execute(run,s['pose_mm'],s['joints'],[g['seat']],cfg,5,
                monitor,reviewed=True,home_transit=True))
            r['steps'].append(dict(kind='seating',result=result));monitor()
        s=preflight(owner);near(s['pose_mm'],g['seat'] if g['phase']=='return_home' else g.get('scanner_target',TARGET),.05)
        r.update(status='at_HOME_held' if g['phase']=='return_home' else 'at_scanner_held',final=s,final_native=native(service))
        return dict(ok=True,record=str(path),status=r['status'],pose_mm=s['pose_mm'])
    except BaseException as e:
        r.update(status='stopped_or_uncertain',error=str(e))
        if r['motion_sent']:
            try:r['stop']=service.program('stop')
            except Exception as stop:r['stop_error']=str(stop)
        raise
    finally:
        if changed:
            try:r['envelope_restoration']=service.set_envelope(*(v for k in ('X','Y','Z') for v in ORIGINAL[k]))
            except Exception as e:r['envelope_restore_error']=str(e)
            if not r.get('envelope_restoration',{}).get('ok'):r['status']='workspace_restoration_failed'
        r['finished_at']=time.time();save()
        if r['status']=='workspace_restoration_failed':raise TransferError('Workspace restoration failed.')


def validate_release(source,d):
    source=Path(source).resolve()
    if source.parent.parent!=OUTPUT.resolve() or source.name!='release_restore.json':
        raise TransferError('Unknown opposite-side release receipt.')
    g=binding(d['plan']['binding']['source'],'release_restore',require_fresh=False)
    if (d.get('status')!='completed' or d.get('payload')!='empty' or not d.get('support_confirmed') or
        d['plan']['binding']!=g or not accepted(d['final_native']['external_axes']['E2']) or
        abs(d['final_native']['external_axes']['E1']-28)>.07):
        raise TransferError('Completed release and original holder restoration required.')
    near(d['final']['pose_mm'],g['station_clearance'],.05)
