"""Reusable Cellvis calibration and accepted HOME station handling.

Keeps commissioning evidence immutable. Each requested run has a unique receipt;
Optional fresh Cellvis calibration runs once before handling; no48-well
calibration substitution, instrument runs, startup, fault clearing or retries.
"""
import hashlib
import json
import math
import re
import secrets
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from autonomy import TransferError
from calibration_e2 import accepted
from holder_contact_monitor import holder_ok
from cellvis24_hamilton_route import instrument_ready as hamilton_ready
from cellvis24_rack_route import reference
from cellvis24_squid_route import geometry, instrument_ready as squid_ready, FOLDER as EVIDENCE
from gripper_closure import closure_commands,grip_feedback_matches
from home_hamilton_exchange import native
from home_squid_transfer import checked
from run_record_io import write_run_record
from scope_step_trial import near, preflight
from trajectory_queue import LuaTrajectory, prepare_points

ROOT=Path(__file__).resolve().parents[1]
RUNS=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'
ACCEPTANCE=EVIDENCE/'accepted_sequence_20261111.json'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence():
    a=json.loads(ACCEPTANCE.read_bytes())
    if a.get('status')!='accepted_commissioned_sequence' or a.get('operator_accepted') is not True:
        raise TransferError('Accepted Cellvis commissioning required.')
    for item in a['evidence'].values():
        if sha(ROOT/item['path'])!=item['sha256']:
            raise TransferError('Accepted Cellvis evidence changed: '+item['path'])
    return sha(ACCEPTANCE)


def settings(stations,cycles,full_calibration=False):
    if type(full_calibration) is not bool:raise TransferError('full_calibration must be boolean.')
    if not isinstance(stations,list) or (not stations and not full_calibration) or len(set(stations))!=len(stations) or any(s not in ('hamilton','squid') for s in stations):
        raise TransferError('Select Hamilton, Squid, or both once in the requested order.')
    if type(cycles) is not int or not 1<=cycles<=100:
        raise TransferError('Choose 1 to100 handling cycles.')
    if not stations and cycles!=1:raise TransferError('Calibration-only runs once; cycles repeat station handling.')


def compile_steps(stations,cycles,full_calibration=False,held_hamilton_roundtrip=False,direct_hamilton=False,taught_hamilton_delivery=False,recorded_hamilton_delivery=False,recorded_hamilton_variant='recorded'):
    if recorded_hamilton_variant not in ('recorded','smooth3','blend3','opposite3') or (recorded_hamilton_variant not in ('recorded','opposite3') and not recorded_hamilton_delivery):
        raise TransferError('Smoothing is only available for recorded Hamilton delivery.')
    rounded_handling=recorded_hamilton_variant=='opposite3' and not recorded_hamilton_delivery
    if rounded_handling and ('hamilton' not in stations or direct_hamilton or taught_hamilton_delivery):
        raise TransferError('Rounded Hamilton handling requires Hamilton and no competing route selection.')
    if type(recorded_hamilton_delivery) is not bool or (recorded_hamilton_delivery and (stations!=['hamilton'] or cycles!=1 or full_calibration or held_hamilton_roundtrip or direct_hamilton or taught_hamilton_delivery)):
        raise TransferError('Recorded Hamilton delivery requires one Hamilton-only run from calibrated HOME.')
    if type(taught_hamilton_delivery) is not bool or (taught_hamilton_delivery and (stations!=['hamilton'] or cycles!=1 or full_calibration or held_hamilton_roundtrip or direct_hamilton)):
        raise TransferError('Taught three-waypoint delivery requires one Hamilton-only run from calibrated HOME.')
    if type(direct_hamilton) is not bool or (direct_hamilton and not held_hamilton_roundtrip):
        raise TransferError('Direct candidate is opt-in for the held Hamilton trial only.')
    if type(held_hamilton_roundtrip) is not bool or (held_hamilton_roundtrip and (stations!=['hamilton'] or full_calibration)):
        raise TransferError('Held Hamilton roundtrip requires Hamilton only and existing HOME calibration.')
    settings(stations,cycles,full_calibration);h=reference();g=geometry();steps=[]
    if direct_hamilton:
        from cellvis24_direct_rack import reference as direct_reference
        h=direct_reference()
    if taught_hamilton_delivery:
        from cellvis24_taught_three_route import reference as taught_reference
        h=taught_reference()
    if recorded_hamilton_delivery or rounded_handling:
        from cellvis24_recorded_hamilton_route import reference as recorded_reference
        h=recorded_reference(recorded_hamilton_variant)
    short=dict(h['routes']['forward']['start']);short['Z']=round(short['Z']-5,2)
    for cycle in range(1,cycles+1):
        for station in stations:
            is_h=station=='hamilton';seat=short if is_h else g['seat']
            clear=dict(seat,Z=round(seat['Z']+30,2));proof=dict(seat,Z=round(seat['Z']+5,2))
            grip=25 if is_h else 3.9;opening=28 if is_h else 7;angle=90.71661229181757 if is_h else 1.77
            forward=h['routes']['forward']['points'] if is_h else g['points']
            reverse=h['routes']['reverse']['points'] if is_h else g['reverse']
            fs=h['routes']['forward']['segment_speeds'] if is_h else g['speeds']
            rs=h['routes']['reverse']['segment_speeds'] if is_h else g['reverse_speeds']
            def add(kind,label,**values):steps.append(dict(kind=kind,label=label,station=station,cycle=cycle,holder_angle=angle,**values))
            def queue(label,points,speed=5,holder=True,**flags):add('queue',label,points=deepcopy(points),speed=speed,holder=holder,flags=flags)
            def jaws(target,speed,holder):add('jaws','Open jaws' if target in (7,28) else 'Close jaws',target=target,speed=speed,holder=holder)
            def close(start,holder):
                for c in closure_commands(start,grip):jaws(c['target_e1_mm'],c['speed'],holder)
                add('observe','Verify settled grip',holder=holder)
            def travel(direction):
                prefix='cellvis24_taught_three_' if taught_hamilton_delivery else ('cellvis24_direct_' if direct_hamilton else 'cellvis24_rack_')
                if recorded_hamilton_delivery or rounded_handling:prefix='cellvis24_opposite_' if recorded_hamilton_variant=='opposite3' else 'cellvis24_smoothed_' if recorded_hamilton_variant in ('smooth3','blend3') else 'cellvis24_recorded_'
                flags=({'hamilton_short_side':prefix+direction} if is_h else {'squid_queue':'cellvis24_home_holder'})
                if is_h and recorded_hamilton_variant in ('blend3','opposite3'):flags['transit_blend']=True
                queue('Travel '+direction,forward if direction=='forward' else reverse,137,False,
                      segment_speeds=fs if direction=='forward' else rs,**flags)
            add('instrument','Check destination idle and loading setup')
            add('rotate','Rotate released HOME holder',target=angle)
            queue('Connect above accepted pickup',[clear],vertical_runs=True)
            if not is_h:queue('First10mm descent',[dict(seat,Z=seat['Z']+20)],137,home_transit=True,home_speed137=True)
            if is_h:queue('Hamilton open-jaw pickup descent',[seat],137,home_transit=True,home_speed137=True)
            else:queue('Final pickup descent',[seat],vertical_runs=True)
            close(28,True);queue('Proof lift5mm',[proof],home_transit=True)
            add('instrument','Check destination before delivery');travel('forward')
            if taught_hamilton_delivery or recorded_hamilton_delivery:
                continue  # Stop holding the plate at Hamilton; no release/return.
            if held_hamilton_roundtrip:
                travel('reverse')
                queue('Reseat in HOME',[seat],home_transit=True)
                jaws(28,5,True)
                queue('Released HOME clearance',[clear],137,home_transit=True,home_speed137=True)
                continue
            jaws(opening,5,False);travel('reverse')
            queue('Empty HOME clearance',[clear],137,home_transit=True,home_speed137=True)
            add('instrument','Check destination before retrieval')
            queue('Empty connector to station route',[proof],137 if is_h else 5,home_transit=True,**({'home_speed137':True} if is_h else {}));travel('forward')
            close(opening,False);travel('reverse')
            queue('Reseat in HOME',[seat],home_transit=True)
            jaws(28,5,True)
            queue('Released HOME clearance',[clear],137,home_transit=True,home_speed137=True)
    return steps


def source_record(source=None):
    if source is None:
        candidates=list(RUNS.glob('*/run.json')) if RUNS.exists() else []
        source=max(candidates,key=lambda p:p.stat().st_mtime) if candidates else EVIDENCE/'squid_release_home.json'
    source=Path(source).resolve();d=json.loads(source.read_bytes())
    if source==EVIDENCE/'squid_release_home.json':
        if d.get('status')!='completed' or d.get('payload')!='empty':raise TransferError('HOME release incomplete.')
    elif source.parent.parent==RUNS.resolve() and source.name=='run.json':
        if d.get('status')!='completed' or d.get('payload')!='empty':raise TransferError('Previous workflow stopped; inspect it before new motion.')
    elif source.name=='release_restore.json':
        from barcode_opposite_transport import validate_release
        validate_release(source,d)
    elif source.name=='hotel_home.json':
        from hotel_cellvis_handoff import validate_source
        validate_source(source,d)
    elif source.name=='recovered_home.json':
        from cellvis_recovery_handoff import validate_source
        validate_source(source,d)
    elif source.name=='reseated_home.json':
        from cellvis24_scanner_return import validate_reseated_source
        validate_reseated_source(source,d)
    else:
        from cellvis24_scanner_return import RUNS as RETURN_RUNS,geometry as return_geometry
        if source.parent.parent!=RETURN_RUNS.resolve() or source.name!='release_home.json' or d.get('status')!='completed' or d.get('payload')!='empty':
            raise TransferError('Use a completed Cellvis HOME release/workflow receipt.')
        if d['plan']['binding']!=return_geometry(source.parent.name):raise TransferError('Scanner-return HOME source changed.')
        seating=source.parent/'return_home.json'
        if sha(seating)!=d['plan']['source_sha256'] or json.loads(seating.read_bytes())['status']!='at_HOME_held':
            raise TransferError('Completed scanner-return seating evidence required.')
    if not 0<=time.time()-d['finished_at']<=1800:raise TransferError('HOME receipt is older than30 minutes; re-establish the plate/setup before reuse.')
    for p in RUNS.glob('*/run.json'):
        if json.loads(p.read_bytes()).get('plan',{}).get('source')==str(source):
            raise TransferError('This starting receipt was already used; use the completed successor or inspect the failure.')
    return source,d


def angle_ok(angle,target):return accepted(angle) if target==1.77 else abs(angle-target)<=.5


def holder_pickup_ready(angle,target):
    """Center the released holder before pickup; contact tolerance is not setup tolerance."""
    return (type(angle) in (int,float) and math.isfinite(angle)
            and (accepted(angle) if target==1.77 else abs(angle-target)<=.05))


def plan(service,cfg,stations,cycles,source=None,full_calibration=False,projected_trial=False,held_hamilton_roundtrip=False,direct_hamilton=False,taught_hamilton_delivery=False,recorded_hamilton_delivery=False,recorded_hamilton_variant='recorded',*,probe=True,check_stations=True,station_check=None):
    if type(projected_trial) is not bool:raise TransferError('projected_trial must be boolean.')
    if projected_trial and (not full_calibration or stations or cycles!=1 or source is not None):
        raise TransferError('Projected calibration trial runs once without grip or station handling.')
    if type(full_calibration) is not bool:raise TransferError('full_calibration must be boolean.')
    if full_calibration and source is not None:raise TransferError('Fresh calibration does not use an old receipt.')
    binding=evidence();steps=compile_steps(stations,cycles,full_calibration,held_hamilton_roundtrip,direct_hamilton,taught_hamilton_delivery,recorded_hamilton_delivery,recorded_hamilton_variant);g=geometry();h=reference()
    s=preflight(service);n=native(service)
    if n['moving'] or not all(math.isfinite(n['external_axes'][k]) for k in ('E1','E2')) or abs(n['external_axes']['E1']-28)>.07:
        raise TransferError('Start stationary with released empty jaws28 and plate supported in HOME.')
    calibration_binding=None;calibration_motion_binding=None;implementation=None
    if full_calibration:
        from cellvis24_calibration import IDLE,REFERENCE,ACCEPTED_SEQUENCE_SHA,reference as camera_reference,compile_steps as calibration_steps
        near(s['pose_mm'],IDLE,.05);camera_reference();calibration_binding=sha(REFERENCE)
        if not accepted(n['external_axes']['E2']):raise TransferError('Restore released holder to original angle at IDLE first.')
        from cellvis24_calibration import projected_trial_steps,implementation_binding
        steps=(projected_trial_steps() if projected_trial else calibration_steps())+steps
        calibration_motion_binding=ACCEPTED_SEQUENCE_SHA
        implementation=implementation_binding()
    else:
        source,d=source_record(source)
        near(s['pose_mm'],d['final']['pose_mm'],.05)
    short=dict(h['routes']['forward']['start']);short['Z']=round(short['Z']+25,2)
    matches=[]
    for pose,angle in [(g['clearance'],1.77),(short,90.71661229181757)]:
        try:near(s['pose_mm'],pose,.05)
        except TransferError:continue
        if angle_ok(n['external_axes']['E2'],angle):matches.append(angle)
    if not full_calibration and len(matches)!=1:raise TransferError('Accepted HOME clearance and matching holder orientation required.')
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
        raise TransferError('Cellvis route settings changed.')
    validate_steps(steps,s,cfg,service.envelope)
    if probe:
        cap=LuaTrajectory(service).capability()
        if not cap.get('available') or cap.get('version')!=220109:raise TransferError('Running mixed-speed Lua220109 required; no startup here.')
        if recorded_hamilton_variant in ('blend3','opposite3'):
            from hamilton_transit_blend import require_capability
            require_capability(service,recorded_hamilton_variant)
        if direct_hamilton:
            reply=service.robot.set_sys_var_i({0:22,1:1,2:0,3:0,4:13,5:0,6:0},reply_timeout=10)
            if reply!={'index':1,'value':220111}:raise TransferError('Publish mixed-wrist queue220111 before the direct trial.')
    for station in stations if check_stations else []:
        if station_check is not None:station_check(station,g)
        else:hamilton_ready() if station=='hamilton' else squid_ready(g)
    return dict(id=uuid4().hex,stations=stations,cycles=cycles,source=str(source) if source else None,source_sha256=sha(source) if source else None,
                full_calibration=full_calibration,calibration_reference_sha256=calibration_binding,
                calibration_motion_sha256=calibration_motion_binding,calibration_implementation=implementation,
                projected_trial=projected_trial,measured_target_pending=projected_trial,held_hamilton_roundtrip=held_hamilton_roundtrip,direct_hamilton=direct_hamilton,taught_hamilton_delivery=taught_hamilton_delivery,recorded_hamilton_delivery=recorded_hamilton_delivery,recorded_hamilton_variant=recorded_hamilton_variant,
                acceptance_sha256=binding,start=s['pose_mm'],joints=s['joints'],e2=n['external_axes']['E2'],steps=steps)


def validate_steps(steps,state,cfg,envelope):
    """Validate the entire remaining route before dispatching its first move."""
    pose=state['pose_mm'];q=state['joints']
    for step in steps:
        if step['kind']=='align':
            from autonomy import alignment_plan
            points=alignment_plan(pose,step['target'],q,cfg,envelope,step['hover_z'])
            q=checked(pose,points,q,cfg,envelope);pose=points[-1]
        if step['kind']=='queue':
            flags=step['flags'];prepare_points(pose,q,step['points'],cfg,reviewed=True,
                **{k:v for k,v in flags.items() if k not in ('segment_speeds','home_speed137','transit_blend')})
            if flags.get('transit_blend'):
                from hamilton_transit_blend import validate as validate_blend
                validate_blend(pose,step['points'],flags.get('hamilton_short_side'),flags.get('segment_speeds'))
            if step['flags'].get('squid_queue'):
                from cellvis24_squid_route import check_route
                q=check_route(pose,step['points'],q,cfg,envelope)
            elif step['flags'].get('hamilton_short_side'):
                from cellvis24_rack_route import validate_route,validate_speeds
                if flags['hamilton_short_side'].startswith('cellvis24_direct_'):
                    from cellvis24_direct_rack import validate_route,validate_speeds
                if flags['hamilton_short_side'].startswith('cellvis24_taught_three_'):
                    from cellvis24_taught_three_route import validate_route,validate_speeds
                if flags['hamilton_short_side'].startswith(('cellvis24_recorded_','cellvis24_smoothed_','cellvis24_opposite_')):
                    from cellvis24_recorded_hamilton_route import validate_route,validate_speeds
                profile=flags['hamilton_short_side'];q=validate_route(pose,step['points'],q,cfg,envelope,profile)
                validate_speeds(pose,step['points'],profile,flags['segment_speeds'])
            else:q=checked(pose,step['points'],q,cfg,envelope)
            pose=step['points'][-1]
    return dict(pose_mm=pose,joints=q)


def execute(run,service,cfg,approved,cam=None):
    fresh=plan(service,cfg,approved['stations'],approved['cycles'],approved['source'],approved.get('full_calibration',False),approved.get('projected_trial',False),approved.get('held_hamilton_roundtrip',False),approved.get('direct_hamilton',False),approved.get('taught_hamilton_delivery',False),approved.get('recorded_hamilton_delivery',False),approved.get('recorded_hamilton_variant','recorded'))
    if fresh['full_calibration'] and cam is None:raise TransferError('Cellvis camera owner unavailable.')
    for key in ('stations','cycles','source','source_sha256','acceptance_sha256','steps','full_calibration','calibration_reference_sha256','calibration_motion_sha256','calibration_implementation','projected_trial'):
        if fresh[key]!=approved.get(key):raise TransferError('Cellvis workflow changed: '+key)
    if fresh['held_hamilton_roundtrip']!=approved.get('held_hamilton_roundtrip',False):raise TransferError('Held Hamilton mode changed.')
    if fresh['direct_hamilton']!=approved.get('direct_hamilton',False):raise TransferError('Hamilton candidate changed.')
    if fresh['taught_hamilton_delivery']!=approved.get('taught_hamilton_delivery',False):raise TransferError('Taught Hamilton delivery mode changed.')
    if fresh['recorded_hamilton_delivery']!=approved.get('recorded_hamilton_delivery',False):raise TransferError('Recorded Hamilton delivery mode changed.')
    if fresh['recorded_hamilton_variant']!=approved.get('recorded_hamilton_variant','recorded'):raise TransferError('Recorded route variant changed.')
    near(fresh['start'],approved['start'],.05)
    if abs(fresh['e2']-approved['e2'])>.05 or any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Starting configuration changed.')
    return execute_checked_steps(run,service,cfg,approved,fresh,cam)


def execute_checked_steps(run,service,cfg,approved,fresh,cam=None,*,initial_e1=28,ends_held=None,receipt_status='completed',station_check=None):
    """Internal executor; callers must regenerate and compare their bound plan first."""
    if not re.fullmatch('[0-9a-f]{32}',approved['id']):raise TransferError('Invalid run ID.')
    folder=RUNS/approved['id'];folder.mkdir(parents=True,exist_ok=False);path=folder/'run.json'
    record=dict(status='running',at=time.time(),plan=approved,steps=[],samples=[],completed_cycles=0,calibration_runs=0,motion_sent=False)
    expected_e1=initial_e1;expected_closed=initial_e1 not in (7,28);expected_angle=fresh['e2'];g=geometry();holder_contact=False
    def save():write_run_record(path,record)
    def check(stationary=False,holder=False,jaws=True):
        s=preflight(service);n=native(service);axes=n['external_axes']
        if run.stopped() or (stationary and n['moving']):raise TransferError('Stopped or unsettled.')
        if not all(math.isfinite(axes[k]) for k in ('E1','E2')):raise TransferError('Invalid axis feedback.')
        jaw_matches=(grip_feedback_matches(axes['E1'],expected_e1,lower_tolerance=.1)
                     if expected_closed else abs(axes['E1']-expected_e1)<=.1)
        if jaws and not jaw_matches:raise TransferError('Jaw position changed.')
        if holder and not holder_ok(axes['E2'],expected_angle,holder_contact):
            raise TransferError(f"HOME holder angle changed: measured E2={axes['E2']:.6f} degrees, target {expected_angle:.6f}.")
        if holder and holder_contact and not angle_ok(axes['E2'],expected_angle):
            record.setdefault('holder_contact_deflections',[]).append(dict(at=time.time(),actual=axes['E2'],target=expected_angle))
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=axes));save();return s,n
    def require_ok(result):
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
            raise TransferError('Command failed or uncertain; no retry: '+str(result))
    def position_released_holder(before,origin,target):
        if expected_e1!=28 or abs(target-origin)>90.01:
            raise TransferError('Holder positioning requires released jaws and a bounded rotation.')
        def rotate():
            current,axes=check(True)
            near(current['pose_mm'],before['pose_mm'],.05)
            if abs(axes['external_axes']['E1']-28)>.07 or abs(axes['external_axes']['E2']-origin)>.05:
                raise TransferError('Holder/jaws changed before positioning.')
            token=secrets.randbelow(1000000)+1
            require_ok(service._hostpoint({7:float(token)},13,5))
            if service.robot.get_sys_var_i([7,8])!={7:token,8:250104}:raise TransferError('Holder interface mismatch.')
            current,axes=check(True);near(current['pose_mm'],before['pose_mm'],.05)
            if abs(axes['external_axes']['E2']-origin)>.05:raise TransferError('Holder changed before rotation.')
            record['motion_sent']=True;save()
            return service._hostpoint({7:float(token),8:origin,9:target},14,120)
        result=service._locked(rotate);require_ok(result);return result
    save()
    try:
        for index,step in enumerate(fresh['steps']):
            item=dict(step,status='checking');record['steps'].append(item);save()
            run.say(f"Cellvis cycle{step['cycle']}/{fresh['cycles']} {step['station']}: {step['label']}")
            if step['kind']=='queue' and step['label']=='Reseat in HOME' and expected_e1<28:
                holder_contact=True
            before,n=check(True,step.get('holder',False));kind=step['kind']
            if kind=='instrument':
                if station_check is not None:station_check(step['station'],g)
                else:hamilton_ready() if step['station']=='hamilton' else squid_ready(g)
            elif kind=='vision':
                from cellvis24_calibration import capture,projected_trial_steps
                def save_vision(value):item['measurement']=value;save()
                measurement=capture(cam,check,folder,save_vision,require_fixed_reference=not fresh['projected_trial'])
                if fresh['projected_trial']:
                    solution=measurement['projected_solution']
                    resolved=projected_trial_steps(solution)
                    current,_=check(True,True)
                    validate_steps(resolved[index+1:],current,cfg,service.envelope)
                    record['resolved_calibration']=dict(solution=solution,steps=resolved,ik_checked=True)
                    fresh['steps'][index+1:]=resolved[index+1:]
                    save()
            elif kind=='align':
                from sequences import seq_align
                check(True,True);record['motion_sent']=True;save()
                item['response']=seq_align(run,service,step['target'],step['hover_z'],translation_speed=step.get('translation_speed',5));require_ok(item['response'])
                current,_=check(True,True)
                near(current['pose_mm'],dict(X=step['target']['x'],Y=step['target']['y'],Z=step['hover_z'],Rz=step['target']['rz']),.05)
            elif kind=='rotate':
                holder_contact=False
                if expected_e1!=28 or abs(n['external_axes']['E1']-28)>.07:raise TransferError('Rotation needs released jaws28.')
                target=step['target'];origin=n['external_axes']['E2']
                if abs(target-origin)>90.01:raise TransferError('Holder segment exceeds published limit.')
                if not holder_pickup_ready(origin,target):
                    item['response']=position_released_holder(before,origin,target)
                expected_angle=target
                for _ in range(3):
                    current,axes=check(True,True);near(current['pose_mm'],before['pose_mm'],.05)
                    if not holder_pickup_ready(axes['external_axes']['E2'],target):
                        raise TransferError('Released holder did not reach pickup angle; no descent or retry.')
                    time.sleep(.1)
            elif kind=='queue':
                record['motion_sent']=True;save()
                executor=LuaTrajectory
                if step['flags'].get('transit_blend'):
                    from hamilton_transit_blend import BlendedTransitTrajectory
                    executor=BlendedTransitTrajectory
                if step['flags'].get('hamilton_short_side','').startswith('cellvis24_direct_'):
                    from cellvis24_direct_rack import MixedWristTrajectory
                    executor=MixedWristTrajectory
                result=executor(service).execute(run,before['pose_mm'],before['joints'],step['points'],cfg,step['speed'],
                    lambda *args:check(holder=step['holder']),reviewed=True,**step['flags'])
                item['response']=result;require_ok(result)
                current,_=check(True,step['holder']);near(current['pose_mm'],step['points'][-1],.05)
            elif kind=='jaws':
                # Plate is at the checked seating pose. Small E2 compliance
                # while closing/lifting is not a new calibration placement.
                closing=step['target']<expected_e1
                item['arrival_tolerance_mm']={'below':.07,'above':.2 if closing else .07}
                if step['holder'] and closing:holder_contact=True
                record['motion_sent']=True;save();result=service.move_gripper(step['target'],step['speed'])
                item['response']=result;save();require_ok(result)
                deadline=time.monotonic()+2;stable=0
                while stable<3:
                    current,n=check(True,step['holder'],False);near(current['pose_mm'],before['pose_mm'],.05)
                    arrived=(grip_feedback_matches(n['external_axes']['E1'],step['target'])
                             if closing else abs(n['external_axes']['E1']-step['target'])<=.07)
                    stable=stable+1 if arrived else 0
                    if time.monotonic()>deadline:raise TransferError('Jaw arrival not verified; no lift.')
                    if stable<3:time.sleep(.1)
                expected_e1=step['target'];expected_closed=closing;torque=service.torque_report();require_ok(torque)
                position_matches=(grip_feedback_matches(torque['e1_position'],expected_e1)
                                  if closing else abs(torque['e1_position']-expected_e1)<=.07)
                if not torque.get('telemetry_live') or not math.isfinite(torque['e1_torque']) or not position_matches:
                    raise TransferError('Fresh settled jaw feedback unavailable.')
                item['torque_report']=torque
            elif kind=='observe':
                for _ in range(20):
                    current,_=check(True,step['holder']);near(current['pose_mm'],before['pose_mm'],.05);time.sleep(.1)
            else:raise TransferError('Unknown workflow step.')
            if kind=='queue' and step['label'] in ('Released HOME clearance','Empty HOME clearance'):
                # Empty arm is clear. Wait for passive settling; do not rotate
                # a held plate or resend an uncertain motion.
                stable=0;deadline=time.monotonic()+1.5;corrected=False
                while stable<3:
                    current,axes=check(True,False)
                    near(current['pose_mm'],step['points'][-1],.05)
                    stable=stable+1 if angle_ok(axes['external_axes']['E2'],expected_angle) else 0
                    if time.monotonic()>deadline:
                        actual=axes['external_axes']['E2']
                        if corrected or expected_e1!=28 or not holder_ok(actual,expected_angle,True):
                            raise TransferError('Released holder did not settle; no new pickup.')
                        run.say('Released holder: correcting small residual angle at HOME clearance.')
                        item['holder_settling_correction']=position_released_holder(current,actual,expected_angle)
                        corrected=True;stable=0;deadline=time.monotonic()+1.5
                    if stable<3:time.sleep(.1)
                holder_contact=False
            item['status']='completed';save()
            if index==len(fresh['steps'])-1 or fresh['steps'][index+1]['cycle']!=step['cycle']:
                if step['station']=='calibration' and not fresh['projected_trial']:record['calibration_runs']=1
                else:record['completed_cycles']=step['cycle']
                save()
        delivery=(fresh['taught_hamilton_delivery'] or fresh['recorded_hamilton_delivery']) if ends_held is None else ends_held
        s,n=check(True,not delivery)
        if fresh['projected_trial']:
            record.update(status='awaiting_open_claw_inspection',final=s,final_native=n,payload='empty',
                          full_calibration_complete=False,grip_authorized=False)
            run.say('Projected alignment and open-jaw descent complete. Inspect centering and gripping height; no grip or transfer was run.')
            return dict(ok=True,status=record['status'],record=str(path),completed_cycles=0,
                        full_calibration_complete=False,grip_authorized=False,pose_mm=s['pose_mm'])
        record.update(status=receipt_status,final=s,final_native=n,payload='held' if delivery else 'empty',operator_retention_observation='pending')
        return dict(ok=True,record=str(path),completed_cycles=record['completed_cycles'],pose_mm=s['pose_mm'])
    except Exception as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        if record['motion_sent']:
            try:record['stop_response']=service.program('stop')
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:record['finished_at']=time.time();save()
