"""Return a completed opposite-wrist delivery, then use taught HOME/Squid handling.

Receipt-bound phases only; no raw route, startup, reset or automatic retry.
The reverse uses the same pinned native corner blends in reverse order.
"""
import json
import math
import time
from pathlib import Path
from uuid import uuid4
from copy import deepcopy
from autonomy import TransferError
import cellvis24_workflow as workflow
from cellvis24_recorded_hamilton_route import reference,plan_path
from scope_step_trial import near,preflight
from home_hamilton_exchange import native
from trajectory_queue import LuaTrajectory
from gripper_closure import grip_feedback_matches


def steps(phase):
    p=reference('opposite3');r=p['routes']['reverse'];f=p['routes']['forward']
    seat=dict(f['start'],Z=round(f['start']['Z']-5,2))
    clear=dict(seat,Z=round(seat['Z']+30,2))
    if phase=='resume_hamilton_pickup':
        items=workflow.compile_steps(['hamilton','squid'],1,recorded_hamilton_variant='opposite3')
        pickup=max(i for i,s in enumerate(items) if s['station']=='hamilton' and s['label']=='Travel forward')
        return [dict(kind='instrument',label='Check Hamilton before reviewed pickup continuation',station='hamilton',cycle=1,holder_angle=90.71661229181757)]+items[pickup+1:]
    if phase=='return_home':
        base=dict(station='hamilton',cycle=1,holder_angle=90.71661229181757)
        return [dict(base,kind='queue',label='Reverse accepted Hamilton route',points=deepcopy(r['points']),speed=137,holder=False,
                     flags=dict(hamilton_short_side='cellvis24_opposite_reverse',segment_speeds=r['segment_speeds'],transit_blend=True)),
                dict(base,kind='queue',label='Reseat in HOME',points=[seat],speed=5,holder=True,flags=dict(home_transit=True)),
                dict(base,kind='jaws',label='Open jaws',target=28,speed=5,holder=True),
                dict(base,kind='queue',label='Released HOME clearance',points=[clear],speed=137,holder=True,flags=dict(home_transit=True,home_speed137=True))]
    if phase=='deliver_squid':
        items=workflow.compile_steps(['squid'],1)
        end=next(i for i,s in enumerate(items) if s['label']=='Travel forward')
        return items[:end+1]
    if phase=='return_squid':
        items=workflow.compile_steps(['squid'],1)
        # Reuse the loaded retrieval's reverse, HOME seating, release and rise.
        begin=max(i for i,s in enumerate(items) if s['label']=='Travel reverse')
        return items[begin:]
    raise TransferError('Unknown continuation phase.')


def source_record(source,phase):
    path=Path(source).resolve()
    if path.parent.parent!=workflow.RUNS.resolve() or path.name!='run.json':
        raise TransferError('Use a completed Cellvis workflow receipt.')
    d=json.loads(path.read_bytes());p=d.get('plan',{})
    resuming=phase=='resume_hamilton_pickup'
    if (not resuming and d.get('status')!='completed') or not 0<=time.time()-d.get('finished_at',0)<=1800:
        raise TransferError('Completed fresh preceding phase required.')
    if resuming:
        expected=workflow.compile_steps(['hamilton','squid'],1,recorded_hamilton_variant='opposite3')
        pickup=max(i for i,s in enumerate(expected) if s['station']=='hamilton' and s['label']=='Travel forward')
        attempted=d.get('steps',[])
        if (d.get('status')!='stopped_or_uncertain' or d.get('error')!='Jaw arrival not verified; no lift.'
                or p.get('steps')!=expected or len(attempted)!=pickup+3
                or attempted[-1].get('target')!=25 or any(x.get('status')!='completed' for x in attempted[:-1])):
            raise TransferError('Only the reviewed Hamilton final-grip stop can continue here.')
        review_path=path.parent/'pickup_recovery_ready.json'
        review=json.loads(review_path.read_bytes())
        if (review.get('source_sha256')!=workflow.sha(path) or review.get('plate_reseated_site4') is not True
                or review.get('empty_jaws_open_verified') is not True or review.get('operator_requested_continuation') is not True
                or not 0<=time.time()-review.get('at',0)<=1800):
            raise TransferError('Fresh reviewed recovery and supported site4 plate required.')
        d=deepcopy(d);d['final']=review['final'];d['recovery_review_sha256']=workflow.sha(review_path)
    elif phase=='return_home':
        if d.get('payload')!='held' or not p.get('recorded_hamilton_delivery') or p.get('recorded_hamilton_variant')!='opposite3':
            raise TransferError('Completed opposite-wrist Hamilton delivery required.')
        travel=p['steps'][-1];r=reference('opposite3')['routes']['forward']
        if travel['points']!=r['points'] or travel['flags'].get('segment_speeds')!=r['segment_speeds']:
            raise TransferError('Completed forward route differs from the reversed route.')
    elif phase=='deliver_squid':
        if d.get('payload')!='empty' or p.get('continuation_phase')!='return_home' or p.get('steps')!=steps('return_home'):
            raise TransferError('Completed released HOME return required.')
        if p.get('route_sha256')!=workflow.sha(plan_path('opposite3')):
            raise TransferError('Return route reference changed.')
    elif phase=='return_squid':
        if d.get('payload')!='held' or p.get('continuation_phase')!='deliver_squid' or p.get('steps')!=steps('deliver_squid'):
            raise TransferError('Completed held Squid delivery required.')
        if p.get('route_sha256')!=workflow.sha(plan_path('opposite3')):
            raise TransferError('Delivery route reference changed.')
    else:raise TransferError('Unknown continuation phase.')
    for previous in workflow.RUNS.glob('*/run.json'):
        if json.loads(previous.read_bytes()).get('plan',{}).get('source')==str(path):
            raise TransferError('Source already used; inspect its successor, no automatic retry.')
    return path,d


def plan(service,cfg,source,phase):
    path,d=source_record(source,phase);items=steps(phase);p=reference('opposite3');g=workflow.geometry()
    s=preflight(service);n=native(service);e1=25 if phase=='return_home' else 3.9 if phase=='return_squid' else 28
    if cfg!=p['config'] or cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
        raise TransferError('IK or workspace configuration changed.')
    if n['moving'] or any(not math.isfinite(n['external_axes'][k]) for k in ('E1','E2')):
        raise TransferError('Stationary valid external-axis feedback required.')
    holder_angle=1.77 if phase=='return_squid' else 90.71661229181757
    grip_matches=(abs(n['external_axes']['E1']-e1)<=.07 if e1==28 else grip_feedback_matches(n['external_axes']['E1'],e1))
    if not grip_matches or not workflow.angle_ok(n['external_axes']['E2'],holder_angle):
        raise TransferError('Grip or HOME holder angle changed.')
    near(s['pose_mm'],d['final']['pose_mm'],.05)
    if any(abs(s['joints'][k]-d['final']['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Joint state differs from completed source.')
    if phase in ('return_home','resume_hamilton_pickup'):workflow.hamilton_ready()
    if phase!='return_home':workflow.squid_ready(g)
    if phase=='resume_hamilton_pickup':near(s['pose_mm'],p['routes']['reverse']['start'],.05)
    validation=workflow.validate_steps(items,s,cfg,service.envelope)
    cap=LuaTrajectory(service).capability()
    if not cap.get('available') or cap.get('version')!=220109:
        raise TransferError('Existing running mixed-speed Lua required.')
    if phase in ('return_home','resume_hamilton_pickup'):
        from hamilton_transit_blend import require_capability
        require_capability(service,'opposite3')
    return dict(id=uuid4().hex,continuation_phase=phase,source=str(path),source_sha256=workflow.sha(path),
        route_sha256=workflow.sha(plan_path('opposite3')),acceptance_sha256=workflow.evidence(),recovery_review_sha256=d.get('recovery_review_sha256'),
        steps=items,start=s['pose_mm'],joints=s['joints'],e2=n['external_axes']['E2'],initial_e1=e1,
        validation=validation,cycles=1,full_calibration=False,projected_trial=False,
        taught_hamilton_delivery=False,recorded_hamilton_delivery=False)


def execute(run,service,cfg,approved):
    fresh=plan(service,cfg,approved['source'],approved['continuation_phase'])
    dynamic={'id','start','joints','e2','validation'}
    if {k:v for k,v in fresh.items() if k not in dynamic}!={k:v for k,v in approved.items() if k not in dynamic}:
        raise TransferError('Continuation plan changed.')
    near(fresh['start'],approved['start'],.05)
    if abs(fresh['e2']-approved['e2'])>.05 or any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Continuation starting state changed.')
    return workflow.execute_checked_steps(run,service,cfg,approved,fresh,
        initial_e1=fresh['initial_e1'],ends_held=fresh['continuation_phase']=='deliver_squid')
