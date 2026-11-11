"""Supervised short-side Hamilton delivery, release, and empty HOME return.

Three separately inspected phases reuse revision04 and the accepted grip25.
No calibration, holder rotation, controller startup, or automatic retries.
"""
from gripper_closure import POLICY, closure_commands
from copy import deepcopy
import json
import math
from pathlib import Path
import time
from uuid import uuid4

import home_hamilton_exchange as exchange
from autonomy import TransferError, check_path
from scope_step_trial import preflight, near
from short_side_hover_transfer import reference, validate_route
from trajectory_queue import LuaTrajectory
from home_seating import seating_plan

FOLDER=exchange.ROOT/'operator_ui/reports/plate_session/hamilton_dropoffs'
STATUSES={'deliver':'at_hamilton_awaiting_support_inspection',
          'release':'released_awaiting_clearance_inspection',
          'return':'empty_at_HOME_clearance',
          'retrieve':'returned_held_at_HOME_seat',
          'finish_home':'plate_released_at_HOME_clearance'}


def evidence(source,phase):
    source=Path(source).resolve()
    allowed=[FOLDER,exchange.FOLDER] if phase in ('deliver','release') else [FOLDER]
    if source.parent not in [p.resolve() for p in allowed]:raise TransferError('Unexpected source receipt location.')
    raw=source.read_bytes();data=json.loads(raw)
    if phase=='release' and source.parent==exchange.FOLDER.resolve() and data.get('plan',{}).get('delivery_only') is not True:
        raise TransferError('Completed delivery-only exchange required for Hamilton release.')
    expected={'deliver':['completed_pending_operator_observation',STATUSES['finish_home']],
        'release':[STATUSES['deliver']], 'return':[STATUSES['release']],
        'retrieve':[STATUSES['return']], 'finish_home':[STATUSES['retrieve']]}[phase]
    if data.get('status') not in expected:raise TransferError('Previous phase did not complete; inspect before any retry.')
    if not 0<=time.time()-data['finished_at']<=1800:raise TransferError('Source receipt is not fresh; recheck setup.')
    for path in FOLDER.glob('*.json'):
        prior=json.loads(path.read_bytes())
        if prior.get('plan',{}).get('source')==str(source) and prior['plan'].get('phase')==phase:
            raise TransferError('This phase was already attempted; inspect its record, no automatic retry.')
    return data,str(source),exchange.digest(source)


def plan(service,cfg,phase,source):
    if phase not in STATUSES:raise TransferError('Unknown drop-off phase.')
    data,source,sha=evidence(source,phase)
    route,_,grip=reference('04');old=data['plan']
    env={k:list(service.envelope[k]) for k in ('X','Y','Z')}
    expected={k:[route['global_envelope'][k]['min'],route['global_envelope'][k]['max']] for k in env}
    if cfg!=route['config'] or env!=expected:raise TransferError('Accepted configuration/workspace changed.')
    for key,value in [('grip',grip),('forward',route['routes']['forward']),('reverse',route['routes']['reverse'])]:
        if old.get(key)!=value:raise TransferError('Accepted route/grip changed: '+key)
    if phase=='deliver' and exchange.digest(exchange.PROFILE)!=exchange.PROFILE_SHA:
        raise TransferError('Calibration pickup profile changed.')
    s=preflight(service);n=exchange.native(service)
    if n['moving']:raise TransferError('Wait for stationary feedback.')
    near(s['pose_mm'],data['final']['pose_mm'],.05)
    e1=25 if phase in ('release','finish_home') else 28
    if not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-e1)>.15:
        raise TransferError('Jaw position differs from the required phase.')
    clearance=dict(grip['descent_endpoint'],Z=grip['descent_endpoint']['Z']+30)
    seating=seating_plan(grip['descent_endpoint']) if phase in ('retrieve','finish_home') else None
    if phase=='finish_home' and old.get('home_seating')!=seating:
        raise TransferError('A fresh retrieval to the continuous HOME seating endpoint is required.')
    q=s['joints'];previous=s['pose_mm'];offset=q['J1']-previous['Z']
    if phase in ('deliver','retrieve','finish_home'):
        if not math.isfinite(n['external_axes']['E2']) or abs(n['external_axes']['E2']-grip['holder_e2_degrees'])>exchange.HOLDER_MONITOR_TOLERANCE_DEG:
            raise TransferError('Rotated holder differs from the accepted pickup angle.')
    if phase in ('deliver','retrieve'):
        near(previous,clearance,.1)
        connector=(grip['alignment'],grip['descent_endpoint'],grip['proof_lift_endpoint']) if phase=='deliver' else (grip['proof_lift_endpoint'],)
        for point in connector:
            q=check_path(previous,point,q,cfg,service.envelope);q['J1']=point['Z']+offset
            if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Joint travel exceeded.')
            previous=point
        for direction in ('forward','reverse'):
            r=route['routes'][direction]
            q=validate_route(r['start'],r['points'],q,cfg,service.envelope,'pickup_hover04_'+direction)
    elif phase in ('release','return'):
        near(previous,route['routes']['reverse']['start'],.1)
        r=route['routes']['reverse']
        q=validate_route(previous,r['points'],q,cfg,service.envelope,'pickup_hover04_reverse')
    else:near(previous,seating['pose'],.1)
    if phase=='retrieve':
        q=check_path(grip['proof_lift_endpoint'],seating['pose'],q,cfg,service.envelope)
        q['J1']=seating['pose']['Z']+offset
        if not 0<=q['J1']<=400:raise TransferError('HOME seating joint travel exceeded.')
    clearance_start=seating['pose'] if seating else grip['proof_lift_endpoint']
    q=check_path(clearance_start,clearance,q,cfg,service.envelope)
    if not 0<=clearance['Z']+offset<=400 or abs(q['J3'])>180:raise TransferError('Clearance joint travel exceeded.')
    steps={'deliver':['Accepted short-side descent','Grip to25','Proof lift5 at5','Accepted forward queue; stop held at Hamilton'],
           'release':['After support inspection: open E1 to28 at speed5; no arm motion'],
           'return':['After release inspection: accepted reverse queue with jaws28','Rise empty to HOME clearance; no reseating'],
           'retrieve':['Approach Hamilton empty at28 using accepted forward queue','Grip to25','Accepted loaded reverse queue','Continuous descent to lowered HOME endpoint at5; stop held'],
           'finish_home':['Release supported plate to28','Return empty to HOME clearance at137']}[phase]
    return dict(id=uuid4().hex,phase=phase,source=source,source_sha256=sha,start=s['pose_mm'],joints=s['joints'],
        closure_policy=POLICY,e1=e1,e2=n['external_axes']['E2'],cfg=cfg,envelope=env,grip=grip,forward=route['routes']['forward'],
        reverse=route['routes']['reverse'],clearance=clearance,home_seating=seating,steps=steps,
        holder_monitor_tolerance_deg=exchange.HOLDER_MONITOR_TOLERANCE_DEG)


def execute(run,service,cfg,approved):
    fresh=plan(service,cfg,approved['phase'],approved['source'])
    for key in ('phase','source','source_sha256','cfg','envelope','grip','forward','reverse','clearance','home_seating','steps','e1','holder_monitor_tolerance_deg','closure_policy'):
        if fresh[key]!=approved.get(key):raise TransferError('Drop-off plan changed: '+key)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Joint configuration changed since preview.')
    if fresh['phase'] in ('deliver','retrieve','finish_home') and abs(fresh['e2']-approved['e2'])>.05:
        raise TransferError('Holder moved since preview.')
    ident=approved.get('id','')
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise TransferError('Invalid plan ID.')
    FOLDER.mkdir(parents=True,exist_ok=True);path=FOLDER/(ident+'.json')
    record=dict(status='started',at=time.time(),plan=deepcopy(approved),phases=[],samples=[],operator_visual_result='pending')
    with path.open('x') as stream:json.dump(record,stream,indent=2)
    def save():path.write_text(json.dumps(record,indent=2))
    g=fresh['grip'];expected_e1=fresh['e1'];holder_required=fresh['phase']=='deliver'
    def check(stationary=False):
        s=service.status();n=exchange.native(service)
        if (run.stopped() or not s.get('connected') or not s.get('ok') or s.get('errors')
                or not s.get('enabled') or s['program_state']['state']!='running'
                or s['control_mode']['mode']!='auto' or not service.envelope_enabled):
            raise TransferError('Drop-off stopped or controller unhealthy.')
        if abs(n['external_axes']['E1']-expected_e1)>.15 or not math.isfinite(n['external_axes']['E1']):
            raise TransferError('Jaw position changed unexpectedly.')
        if holder_required and (not math.isfinite(n['external_axes']['E2']) or
                abs(n['external_axes']['E2']-g['holder_e2_degrees'])>exchange.HOLDER_MONITOR_TOLERANCE_DEG):
            raise TransferError('Holder changed before pickup.')
        if stationary and n['moving']:raise TransferError('Motion not settled.')
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
        return s
    def queue(label,points,speed,**flags):
        run.say(label);s=check(True)
        item=dict(label=label,status='dispatching',points=points,speed=speed);record['phases'].append(item);save()
        result=LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],points,cfg,speed,
            lambda *args:check(),reviewed=True,**flags)
        if not result.get('ok') or result.get('recovered'):raise TransferError(label+' failed or uncertain.')
        s=check(True);near(s['pose_mm'],points[-1],.1)
        item.update(status='completed',result=result);save()
    def jaws(target,pose,speed=5):
        nonlocal expected_e1
        before=check(True);near(before['pose_mm'],pose,.1)
        item=dict(label='Jaw move',target=target,speed=speed,status='dispatching');record['phases'].append(item);save()
        result=service.move_gripper(target,speed);item['response']=result;save()
        if not result.get('ok') or result.get('recovered'):raise TransferError('Jaw movement uncertain; no retry.')
        if target<expected_e1 and result.get('gripper',{}).get('grip_detected'):
            raise TransferError('Unexpected closing contact/stall; stop before lifting.')
        expected_e1=target;s=check(True);near(s['pose_mm'],before['pose_mm'],.05)
        item.update(status='completed',result=result);save()
    try:
        check(True)
        if fresh['phase']=='deliver':
            queue('Connect to accepted alignment',[g['alignment']],5)
            queue('Accepted short-side descent',[g['descent_endpoint']],137,home_transit=True,home_speed137=True)
            for command in closure_commands(28, g['target_e1_mm']):
                jaws(command['target_e1_mm'],g['descent_endpoint'],command['speed'])
                for _ in range(3):check(True);time.sleep(.15)
            holder_required=False
            queue('Proof lift5 at speed5',[g['proof_lift_endpoint']],5,home_transit=True)
            r=fresh['forward'];queue('Accepted Hamilton overhead entry',r['points'],137,
                hamilton_short_side='pickup_hover04_forward',segment_speeds=r['segment_speeds'])
        elif fresh['phase']=='release':
            jaws(28,fresh['reverse']['start'])
        elif fresh['phase']=='return':
            r=fresh['reverse'];queue('Accepted reverse queue, empty jaws',r['points'],137,
                hamilton_short_side='pickup_hover04_reverse',segment_speeds=r['segment_speeds'])
            queue('Raise empty to HOME clearance',[fresh['clearance']],137,home_transit=True,home_speed137=True)
        elif fresh['phase']=='retrieve':
            queue('Empty connection to accepted forward start',[g['proof_lift_endpoint']],137,home_transit=True,home_speed137=True)
            r=fresh['forward'];queue('Approach Hamilton empty at28',r['points'],137,
                hamilton_short_side='pickup_hover04_forward',segment_speeds=r['segment_speeds'])
            for command in closure_commands(28, g['target_e1_mm']):
                jaws(command['target_e1_mm'],fresh['reverse']['start'],command['speed'])
                for _ in range(3):check(True);time.sleep(.15)
            r=fresh['reverse'];queue('Retrieve via accepted reverse queue',r['points'],137,
                hamilton_short_side='pickup_hover04_reverse',segment_speeds=r['segment_speeds'])
            holder_required=True;check(True)
            seating=fresh['home_seating']
            queue('Continuous HOME seating descent',[seating['pose']],seating['speed'],home_transit=True)
        else:
            holder_required=True;check(True)
            seating=fresh['home_seating']
            jaws(28,seating['pose'])
            queue('Return empty to HOME clearance',[fresh['clearance']],137,home_transit=True,home_speed137=True)
        s=check(True);record.update(status=STATUSES[fresh['phase']],final=s)
        return dict(ok=True,record=str(path),status=record['status'],pose_mm=s['pose_mm'],
                    payload='held_pending_inspection' if fresh['phase'] in ('deliver','retrieve') else 'empty')
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error));raise
    finally:
        record['finished_at']=time.time();save();run.audit('hamilton_holder_dropoff',record=str(path))
