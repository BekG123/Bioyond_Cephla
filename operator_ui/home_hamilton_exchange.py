"""Supervised HOME-holder/Hamilton round trip; no IDLE or controller recovery.

Uses the accepted revision-04 Hamilton queue in both directions. The new
near-holder connection is restricted to the completed calibration clearance.
"""
from gripper_closure import POLICY, closure_commands
from home_seating import seating_plan
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import secrets
import time
from uuid import uuid4

from autonomy import TransferError, check_path
from calibration_e2 import accepted
from draggo import DragGoRPC
from scope_step_trial import preflight, near
from short_side_hover_transfer import reference, validate_route
from trajectory_queue import LuaTrajectory

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'operator_ui/reports/plate_session/hamilton_exchanges'
PROFILE=ROOT/'Pick and Hold/Calibration/plate_48_pickup_profile.json'
PROFILE_SHA='1ddb2a2a3029eacb34317581d204cca62c68fc992420c49140e9b8efee0a09bc'
KEYS=('X','Y','Z','Rz')
# Keep commanded rotation arrival tight; allow small subsequent readback drift.
HOLDER_ARRIVAL_TOLERANCE_DEG=.10
HOLDER_MONITOR_TOLERANCE_DEG=.5
# Lua permits 90.01 degrees per command. Keep 0.11 degrees of margin for
# the existing 0.10-degree pre-dispatch readback check, without splitting
# an ordinary ~89.65-degree restoration into two equal half-turns.
HOLDER_RESTORE_MAX_STEP_DEG=89.9


def holder_restore_targets(origin,target=1.77):
    """Absolute restoration within the published Lua +/-360-degree bounds.

    Leave readback margin below its 90.01-degree per-command bound. Do not wrap
    the angle to an equivalent winding or remove any controller limit.
    """
    if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>360 for v in (origin,target)):
        raise TransferError('Holder feedback/target must be finite and within the published +/-360-degree range.')
    count=math.ceil(abs(target-origin)/HOLDER_RESTORE_MAX_STEP_DEG)
    return [target if i==count else origin+(target-origin)*i/count for i in range(1,count+1)]


def restore_original(run,service):
    """Restore released holder at IDLE between explicitly requested repetitions."""
    from calibration_e2 import TARGET_DEGREES, calibration_ready
    from repeat_holder_calibration_20261110 import at_idle_pose
    FOLDER.mkdir(parents=True,exist_ok=True)
    path=FOLDER/('restore_'+uuid4().hex+'.json')
    record=dict(status='checking',at=time.time(),target=TARGET_DEGREES,motion_sent=False,samples=[],segments=[])
    def save():path.write_text(json.dumps(record,indent=2))
    def check():
        s=preflight(service);n=native(service)
        if run.stopped() or n['moving']:raise TransferError('Stopped or moving during holder restoration.')
        if not at_idle_pose(s['pose_mm']):raise TransferError('Holder restoration requires the UI-accepted IDLE position.')
        if not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-28)>.15:
            raise TransferError('Holder restoration requires released empty jaws at28 mm.')
        e2=n['external_axes']['E2']
        if not math.isfinite(e2):raise TransferError('Invalid holder angle.')
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
        return s,n
    try:
        before,n=check();origin=n['external_axes']['E2'];record['origin']=origin;save()
        targets=holder_restore_targets(origin,TARGET_DEGREES)
        if not calibration_ready(origin):
            record['planned_targets']=targets;save()
            expected=origin
            for index,target in enumerate(targets,1):
                run.say(f'Restore holder to1.77 degrees: segment {index}/{len(targets)}, target {target:.3f}.')
                item=dict(target=target,status='checking');record['segments'].append(item);save()
                def rotate():
                    current_state,current=check();near(current_state['pose_mm'],before['pose_mm'],.05)
                    measured=current['external_axes']['E2']
                    if abs(measured-expected)>.1:raise TransferError('Holder changed before restore segment.')
                    if abs(target-measured)>90.01 or abs(measured)>360:raise TransferError('Holder segment exceeds published limits.')
                    token=secrets.randbelow(1000000)+1
                    probe=service._hostpoint({7:float(token)},13,5)
                    if not probe.get('ok'):raise TransferError('Holder capability probe failed.')
                    regs=service.robot.get_sys_var_i([7,8])
                    if regs.get(7)!=token or regs.get(8)!=250104:raise TransferError('Published holder interface mismatch.')
                    if run.stopped():raise TransferError('Stopped before restore.')
                    record['motion_sent']=True;item.update(status='dispatching',origin=measured);save()
                    result=service._hostpoint({7:float(token),8:measured,9:target},14,120)
                    if not result.get('ok') or result.get('recovered'):raise TransferError('Holder restore uncertain; no retry.')
                    s,n=check();near(s['pose_mm'],before['pose_mm'],.05)
                    if abs(n['external_axes']['E2']-target)>.1:raise TransferError('Holder segment arrival mismatch; no retry.')
                    item.update(status='completed',result=result,actual=n['external_axes']['E2']);save()
                    return result
                result=service._locked(rotate)
                if not result.get('ok'):raise TransferError('Holder restore did not complete.')
                expected=target
        for _ in range(3):
            s,n=check();near(s['pose_mm'],before['pose_mm'],.05)
            actual=n['external_axes']['E2']
            if not accepted(actual):
                raise TransferError(f'Original holder arrival mismatch: E2={actual:.6f} degrees; '
                                    f'target {TARGET_DEGREES:.3f}, accepted 1.740–1.820; no retry.')
            time.sleep(.1)
        record.update(status='completed',final=s)
        return dict(ok=True,record=str(path),actual_e2=n['external_axes']['E2'],motion_sent=record['motion_sent'])
    except Exception as e:
        record.update(status='failed_or_uncertain',error=str(e));raise
    finally:
        record['finished_at']=time.time();save()


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def calibration_evidence(path):
    path=Path(path).resolve()
    if ROOT/'operator_ui/reports/plate_session' not in path.parents:
        raise TransferError('Use this session calibration receipt.')
    data=json.loads(path.read_bytes())
    if data.get('status')!='calibration_completed_at_HOME' or digest(PROFILE)!=PROFILE_SHA:
        raise TransferError('Completed unchanged calibration is required.')
    phase=data['phases'][-1]
    if phase['phase']!='calibration' or phase['status']!='completed':
        raise TransferError('Calibration did not finish.')
    result=phase['sequence']['result'];receipt=Path(result['record']).resolve()
    if ROOT/'operator_ui/demonstrations/pickup_holder' not in receipt.parents:
        raise TransferError('Unexpected calibration completion receipt.')
    proof=json.loads(receipt.read_bytes())
    if (proof.get('status')!='completed' or proof.get('action')!='Clearance'
            or result.get('payload')!='empty' or not result.get('ok')
            or not 0<=time.time()-proof['finished_at']<=1800):
        raise TransferError('Fresh released-plate clearance receipt required.')
    return data,dict(calibration_record=str(path),calibration_sha256=digest(path),
                     clearance_record=str(receipt),clearance_sha256=digest(receipt))


def native(service):
    n=DragGoRPC(service._endpoint_addr()[0]).info()
    if any(n.get(k,True) for k in ('error','emergency','drag','manual')):
        raise TransferError('Unhealthy controller or hand-guiding; no reset/retry.')
    if n.get('external_units',{}).get('E2')!='degrees':
        raise TransferError('Holder-angle feedback unavailable.')
    return n


def plan(service,cfg,calibration_record,delivery_only=False):
    if type(delivery_only) is not bool:raise TransferError("Invalid delivery mode.")
    data,binding=calibration_evidence(calibration_record)
    s=preflight(service);n=native(service)
    if n['moving'] or abs(n['external_axes']['E1']-28)>.15 or not accepted(n['external_axes']['E2']):
        raise TransferError('Stationary original holder and open empty jaws required.')
    near(s['pose_mm'],data['final']['pose_mm'],.05)
    p,_,g=reference('04')
    if cfg!=p['config']:raise TransferError('Accepted IK configuration changed.')
    env={k:tuple(service.envelope[k]) for k in ('X','Y','Z')}
    expected={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in env}
    if env!=expected:raise TransferError('Workspace changed.')
    previous=s['pose_mm'];q=s['joints'];offset=q['J1']-previous['Z']
    # Short connection is commissioned at speed 5; existing descent remains 137.
    for point in (g['alignment'],g['descent_endpoint'],g['proof_lift_endpoint']):
        q=check_path(previous,point,q,cfg,env);q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Joint travel exceeded.')
        previous=point
    for direction in ('forward','reverse'):
        r=p['routes'][direction]
        q=validate_route(r['start'],r['points'],q,cfg,env,'pickup_hover04_'+direction)
    seating=seating_plan(g['descent_endpoint']) if not delivery_only else None
    if seating:
        q=check_path(g['proof_lift_endpoint'],seating['pose'],q,cfg,env)
        q['J1']=seating['pose']['Z']+offset
        if not 0<=q['J1']<=400:raise TransferError('HOME seating joint travel exceeded.')
        check_path(seating['pose'],dict(g['descent_endpoint'],Z=g['descent_endpoint']['Z']+30),q,cfg,env)
    return dict(id=uuid4().hex,start=s['pose_mm'],joints=s['joints'],e2=n['external_axes']['E2'],
        closure_policy=POLICY,delivery_only=delivery_only,cfg=cfg,envelope={k:list(v) for k,v in env.items()},binding=binding,grip=g,forward=p['routes']['forward'],
        reverse=p['routes']['reverse'],home_seating=seating,idle_travel=False,holder_target_degrees=g['holder_e2_degrees'],
        holder_tolerances_deg=dict(arrival=HOLDER_ARRIVAL_TOLERANCE_DEG,monitor=HOLDER_MONITOR_TOLERANCE_DEG),
        steps=['Rotate released holder','Connect to short-side alignment','Descend',
               'Grip short side','Lift 5 mm slowly','Hamilton via taught hover',
               *(['Stop held at Hamilton for supported release'] if delivery_only else
                 ['Reverse taught queue to HOME','Continuous seating descent at5','Release','Return empty to HOME clearance'])])


def execute(run,service,cfg,approved):
    if not isinstance(approved.get('id'),str) or len(approved['id'])!=32 or any(c not in '0123456789abcdef' for c in approved['id']):
        raise TransferError('Invalid exchange plan identifier.')
    fresh=plan(service,cfg,approved['binding']['calibration_record'],approved.get('delivery_only',False))
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Arm configuration changed since review.')
    for key in ('binding','cfg','envelope','grip','forward','reverse','home_seating','holder_tolerances_deg','closure_policy','delivery_only'):
        if fresh[key]!=approved.get(key):raise TransferError('Reviewed exchange changed: '+key)
    if abs(fresh['e2']-approved['e2'])>.05:raise TransferError('Holder moved since review.')
    FOLDER.mkdir(parents=True,exist_ok=True)
    path=FOLDER/(approved['id']+'.json')
    record=dict(status='started',at=time.time(),plan=approved,phases=[],samples=[],
                idle_travel=False,controller_restart=False,operator_visual_result='pending')
    with path.open('x') as f:json.dump(record,f,indent=2)
    def save():path.write_text(json.dumps(record,indent=2))
    g=fresh['grip'];expected_e1=28;holder_required=True;holder_target=fresh['e2']
    holder_tolerance=HOLDER_ARRIVAL_TOLERANCE_DEG
    def check(stationary=False):
        s=service.status();n=native(service)
        record['samples'].append(dict(at=time.time(),pose=s.get('pose_mm'),axes=n['external_axes'],
            holder_required=holder_required,holder_target=holder_target,holder_tolerance=holder_tolerance));save()
        if (run.stopped() or not s.get('connected') or not s.get('ok') or s.get('errors')
                or not s.get('enabled') or s['program_state']['state']!='running'
                or s['control_mode']['mode']!='auto' or not service.envelope_enabled):
            raise TransferError('Exchange stopped or controller not ready.')
        if not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-expected_e1)>.15:
            raise TransferError('Jaw position changed unexpectedly.')
        e2=n['external_axes']['E2']
        if not math.isfinite(e2) or (holder_required and abs(e2-holder_target)>holder_tolerance):
            raise TransferError(f"Holder angle changed before seating/grasp: actual {e2:.6f}, target {holder_target:.6f} degrees; tolerance {holder_tolerance:.2f}.")
        if stationary and n['moving']:raise TransferError('Arm has not settled.')
        return s,n
    def queue(label,points,speed,**flags):
        run.say(label);s,_=check(True)
        item=dict(label=label,status='dispatching',points=points,speed=speed);record['phases'].append(item);save()
        result=LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],points,cfg,speed,
            lambda *args:check(),reviewed=True,**flags)
        if not result.get('ok'):raise TransferError(label+' did not complete.')
        s,_=check(True);near(s['pose_mm'],points[-1],.1)
        item.update(status='completed',result=result,final=s['pose_mm']);save()
    def jaws(target,speed=5,pose=None):
        nonlocal expected_e1
        before,_=check(True);near(before['pose_mm'],pose or g['descent_endpoint'],.1)
        item=dict(label='Jaw move',target=target,speed=speed,status='dispatching');record['phases'].append(item);save()
        result=service.move_gripper(target,speed);item['response']=result;save()
        if not result.get('ok') or result.get('recovered'):raise TransferError('Jaw command failed or uncertain.')
        if target<expected_e1 and result.get('gripper',{}).get('grip_detected'):
            raise TransferError('Unexpected closure contact/stall; stop before lift.')
        expected_e1=target;s,_=check(True);near(s['pose_mm'],before['pose_mm'],.05)
        item.update(status='completed',result=result);save()
    try:
        check(True);run.say('Rotate released HOME holder to taught short-side angle.')
        token=secrets.randbelow(1000000)+1
        def rotate():
            before,_=check(True)
            result=service._hostpoint({7:float(token)},13,5)
            if not result.get('ok'):raise TransferError('Rotation capability probe failed.')
            regs=service.robot.get_sys_var_i([7,8])
            if regs.get(7)!=token or regs.get(8)!=250104:raise TransferError('Published holder interface mismatch.')
            if run.stopped():raise TransferError('Stopped before rotation.')
            record['rotation_dispatched']=True;save()
            result=service._hostpoint({7:float(token),8:fresh['e2'],9:g['holder_e2_degrees']},14,120)
            if not result.get('ok'):raise TransferError('Rotation failed/uncertain; no retry.')
            near(service.pose_mm(),before['pose_mm'],.05)
            return result
        record['rotation_result']=service._locked(rotate)
        if not record['rotation_result'].get('ok'):raise TransferError('Rotation lock/command failed.')
        holder_target=g['holder_e2_degrees']
        for _ in range(3):check(True);time.sleep(.1)
        holder_tolerance=HOLDER_MONITOR_TOLERANCE_DEG
        queue('Short connection above rotated plate',[g['alignment']],5)
        queue('Accepted 30 mm short-side descent',[g['descent_endpoint']],137,home_transit=True,home_speed137=True)
        for command in closure_commands(28, g['target_e1_mm']):
            jaws(command['target_e1_mm'],command['speed'])
            for _ in range(3):check(True);time.sleep(.15)
        holder_required=False
        queue('Lift short-side grip 5 mm slowly',[g['proof_lift_endpoint']],5,home_transit=True)
        directions=[('forward','Hamilton taught overhead entry')]
        if not fresh['delivery_only']:directions.append(('reverse','Return directly to HOME holder'))
        for direction,label in directions:
            route=fresh[direction]
            queue(label,route['points'],137,hamilton_short_side='pickup_hover04_'+direction,
                  segment_speeds=route['segment_speeds'])
        if fresh['delivery_only']:
            s,_=check(True);record.update(status='at_hamilton_awaiting_support_inspection',final=s)
            return dict(ok=True,record=str(path),pose_mm=s['pose_mm'],payload='held',station='Hamilton',idle_travel=False)
        holder_required=True;check(True)
        seating=fresh['home_seating']
        queue('Continuous HOME seating descent',[seating['pose']],seating['speed'],home_transit=True)
        jaws(28,pose=seating['pose'])
        queue('Return empty to HOME clearance',[dict(g['descent_endpoint'],Z=g['descent_endpoint']['Z']+30)],
              137,home_transit=True,home_speed137=True)
        s,_=check(True);record.update(status='completed_pending_operator_observation',final=s)
        return dict(ok=True,record=str(path),pose_mm=s['pose_mm'],payload='empty',station='HOME',idle_travel=False)
    except Exception as e:
        record.update(status='failed_or_uncertain',error=str(e));raise
    finally:
        record['finished_at']=time.time();save();run.audit('home_hamilton_exchange',record=record)
