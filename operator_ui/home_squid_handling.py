"""Chain saved Squid release/retrieval onto the reviewed direct HOME route.

No new coordinates, controller startup, fault recovery or automatic retries.
Release at Squid uses the established 7 mm opening; pickup closes to3.9 at5.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import time
from uuid import uuid4

import home_squid_transfer as route
from autonomy import TransferError
from calibration_e2 import accepted
from gripper_closure import POLICY, closure_commands
from scope_step_trial import preflight, near
from trajectory_queue import LuaTrajectory

STATUSES = {'release_squid':'plate_released_at_squid',
            'empty_return':'empty_at_HOME_clearance',
            'retrieve':'returned_held_at_HOME_seat'}


def plan(service,cfg,source,phase):
    if phase not in STATUSES:raise TransferError('Unknown Squid handling phase.')
    source=Path(source).resolve()
    if source.parent!=route.FOLDER.resolve():raise TransferError('Unexpected Squid receipt.')
    data=json.loads(source.read_bytes())
    expected={'release_squid':'at_squid_held_pending_operator_assessment',
              'empty_return':STATUSES['release_squid'], 'retrieve':STATUSES['empty_return']}[phase]
    if data.get('status')!=expected or not 0<=time.time()-data['finished_at']<=1800:
        raise TransferError('Fresh completed predecessor required.')
    for path in route.FOLDER.glob('*.json'):
        if json.loads(path.read_bytes()).get('plan',{}).get('source')==str(source):
            raise TransferError('Predecessor already used; inspect, no retry.')
    g=route.geometry()
    if data['plan']['geometry']!=g:raise TransferError('Pickup/Squid geometry changed.')
    s=preflight(service);n=route.exchange.native(service)
    expected_e1=3.9 if phase=='release_squid' else 7
    if n['moving'] or not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-expected_e1)>.1:
        raise TransferError('Stationary expected gripper position required.')
    if not accepted(n['external_axes']['E2']):raise TransferError('Original HOME holder orientation required.')
    near(s['pose_mm'],data['final']['pose_mm'],.05)
    near(s['pose_mm'],g['clearance'] if phase=='retrieve' else g['points'][-1],.05)
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
        raise TransferError('Route configuration changed.')
    reverse=list(reversed([g['proof']]+g['points'][:-1]));q=s['joints']
    if phase=='retrieve':
        # This connector retraces the already used HOME vertical clearance.
        q=route.checked(g['clearance'],[g['proof']],q,cfg,service.envelope)
        q=route.check_route(g['proof'],g['points'],q,cfg,service.envelope)
    q=route.check_route(g['points'][-1],reverse,q,cfg,service.envelope)
    seating=route.seating_plan(g['seat']) if phase=='retrieve' else None
    route.checked(g['proof'],[seating['pose'] if seating else g['clearance']],q,cfg,service.envelope)
    return dict(id=uuid4().hex,phase=phase,source=str(source),
        source_sha256=route.exchange.digest(source),closure_policy=POLICY,
        geometry=g,start=s['pose_mm'],joints=s['joints'],e1=expected_e1,home_seating=seating,
        reverse=reverse,reverse_speeds=[5,137,137,137])


def execute(run,service,cfg,approved):
    fresh=plan(service,cfg,approved['source'],approved['phase'])
    for key in ('phase','source','source_sha256','closure_policy','geometry','e1','home_seating','reverse','reverse_speeds'):
        if approved.get(key)!=fresh[key]:raise TransferError('Squid handling plan changed: '+key)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Starting joint configuration changed.')
    ident=approved.get('id','')
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise TransferError('Invalid plan ID.')
    path=route.FOLDER/(ident+'.json');g=fresh['geometry'];expected_e1=fresh['e1']
    record=dict(status='started',at=time.time(),plan=deepcopy(approved),phases=[],samples=[],
                operator_retention_result='pending',controller_restart=False)
    with path.open('x') as stream:json.dump(record,stream,indent=2)
    def save():path.write_text(json.dumps(record,indent=2))
    def check(stationary=False,holder=False):
        if run.stopped():raise TransferError('Squid handling stopped.')
        s=preflight(service);n=route.exchange.native(service)
        if stationary and n['moving']:raise TransferError('Motion not settled.')
        value=n['external_axes']['E1']
        if not math.isfinite(value) or abs(value-expected_e1)>.1:raise TransferError('Grip feedback changed.')
        if holder and not accepted(n['external_axes']['E2']):raise TransferError('Holder moved before HOME approach.')
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
        return s
    def queue(label,points,speed,holder=False,**flags):
        s=check(True,holder);run.say(label)
        item=dict(label=label,status='dispatching',points=points,speed=speed);record['phases'].append(item);save()
        result=LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],points,cfg,speed,
            lambda *args:check(holder=holder),reviewed=True,**flags)
        if not result.get('ok') or result.get('recovered'):raise TransferError('Uncertain Squid motion; no retry.')
        s=check(True,holder);near(s['pose_mm'],points[-1],.1)
        item.update(status='completed',result=result);save()
    def jaws(target,speed=5):
        nonlocal expected_e1
        before=check(True);near(before['pose_mm'],g['points'][-1],.1)
        item=dict(label='Squid jaws',target=target,speed=speed,status='dispatching');record['phases'].append(item);save()
        result=service.move_gripper(target,speed);item['response']=result;save()
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
            raise TransferError('Uncertain Squid gripper movement; no retry or lift.')
        # Same three settled readings as the saved Squid pickup/release skill.
        expected_e1=target
        for _ in range(3):
            time.sleep(.25);s=check(True);near(s['pose_mm'],before['pose_mm'],.05)
        item['status']='completed';save()
    try:
        check(True,True)
        if fresh['phase']=='release_squid':
            run.say('Release supported plate at Squid to7 mm at speed5.')
            jaws(7)
        elif fresh['phase']=='empty_return':
            queue('Empty Squid departure and direct HOME return',fresh['reverse'],137,
                  squid_queue='home_holder',segment_speeds=fresh['reverse_speeds'])
            queue('Empty HOME clearance',[g['clearance']],137,holder=True,home_transit=True,home_speed137=True)
        else:
            queue('Empty connection to taught HOME departure',[g['proof']],5,holder=True,home_transit=True)
            queue('Approach Squid with open jaws',g['points'],137,
                  squid_queue='home_holder',segment_speeds=g['speeds'])
            run.say('Grip at Squid: approach at10, final1mm at5.')
            for command in closure_commands(7,3.9):jaws(command['target_e1_mm'],command['speed'])
            queue('Loaded Squid departure and direct HOME return',fresh['reverse'],137,
                  squid_queue='home_holder',segment_speeds=fresh['reverse_speeds'])
            seating=fresh['home_seating']
            queue('Continuous HOME seating descent',[seating['pose']],seating['speed'],holder=True,home_transit=True)
        s=check(True,True);record.update(status=STATUSES[fresh['phase']],final=s)
        return dict(ok=True,status=record['status'],record=str(path),pose_mm=s['pose_mm'],
                    payload='held' if fresh['phase']=='retrieve' else 'empty')
    except Exception as error:record.update(status='failed_or_uncertain',error=str(error));raise
    finally:record['finished_at']=time.time();save();run.audit('home_squid_handling',record=str(path))
