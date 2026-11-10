"""Pinned open-jaw approach trials; corrected02 includes the taught descent."""
import hashlib
import json
import math
from pathlib import Path
import time
from autonomy import TransferError, check_path
from draggo import DragGoRPC
from scope_step_trial import near, preflight

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'reports/holder_short_side/alignment'
PLAN_SHA='defca78bddc86066b4082d2d39f04a4c3067f8b98d478d080f9146dfdfc6c284'
CORRECTED02_SHA='a94646c94465b984e1ce215b49297e979813a1c8cb40f66357de7fb6fb949794'


def reference():
    raw=(FOLDER/'plan.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PLAN_SHA:raise TransferError('Reviewed alignment candidate changed')
    plan=json.loads(raw)
    taught_raw=(FOLDER/'taught_alignment.json').read_bytes()
    if hashlib.sha256(taught_raw).hexdigest()!=plan['source_sha256']:raise TransferError('Taught alignment changed')
    if hashlib.sha256((ROOT/'points.json').read_bytes()).hexdigest()!=plan['home_source_sha256']:raise TransferError('Saved Home changed')
    return plan,json.loads(taught_raw)


def reference_for_candidate(candidate):
    plan,taught=reference()
    if candidate!='corrected02':return plan,taught
    raw=(ROOT.parent/'Pick and Hold/Descend/short_side_taught_endpoint.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=CORRECTED02_SHA:raise TransferError('Corrected short-side profile changed')
    settings=json.loads(raw)
    capture_raw=(FOLDER/'corrected_alignment_02.json').read_bytes()
    if hashlib.sha256(capture_raw).hexdigest()!=settings['evidence_sha256']:raise TransferError('Corrected teaching evidence changed')
    capture=json.loads(capture_raw)
    if capture['home_source_sha256']!=plan['home_source_sha256']:raise TransferError('Corrected Home source changed')
    if settings['descent_drop_mm']!=30 or settings['approach_speed']!=137 or settings['descent_speed']!=137 or settings['gripper_open_e1_mm']!=28:raise TransferError('Incorrect corrected trial settings')
    alignment=settings['alignment'];end=settings['endpoint']
    if any(end[k]!=alignment[k] for k in ('X','Y','Rz')) or abs(alignment['Z']-end['Z']-30)>1e-8:raise TransferError('Descent must be vertical 30 mm')
    plan=dict(plan,goal=end,corrected_points=capture['transmitted_candidate'],profile_sha256=CORRECTED02_SHA)
    taught=dict(taught,target=alignment,taught_joints=capture['samples'][-1]['robot']['joints'],
        config=capture['config'],envelope=capture['envelope'],e2_degrees=settings['holder_e2_degrees'])
    return plan,taught


def candidate_points(plan,candidate):
    if candidate=='corrected02':return plan['corrected_points']
    if candidate in ('smooth_direct','smooth_repeat01'):
        # Same pinned line and endpoint, with no intermediate command boundaries.
        return [dict(plan['candidates']['direct']['points'][-1])]
    if candidate not in ('direct','clearance'):raise TransferError('Unknown alignment candidate')
    if not plan['candidates'][candidate]['ik_valid']:raise TransferError('Unvalidated alignment candidate')
    return plan['candidates'][candidate]['points']


def validate_shape(start,points,candidate):
    plan,_=reference_for_candidate(candidate)
    if points!=candidate_points(plan,candidate):raise TransferError('Queue differs from the pinned alignment route')
    near(start,plan['home'],.1)


def validate_route(start,points,joints,cfg,envelope,candidate):
    plan,taught=reference_for_candidate(candidate)
    validate_shape(start,points,candidate)
    if cfg!=taught['config']:raise TransferError('IK configuration changed')
    env={k:(taught['envelope'][k]['min'],taught['envelope'][k]['max']) for k in ('X','Y','Z')}
    if {k:tuple(v) for k,v in envelope.items()}!=env:raise TransferError('Workspace changed')
    for key in ('J1','J2','J3','J4'):
        if abs(joints[key]-plan['home_joints'][key])>.5:raise TransferError('Home joint configuration changed')
    q=dict(joints);previous=start;offset=joints['J1']-start['Z']
    for point in points:
        q=check_path(previous,point,q,cfg,env);q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Joint travel exceeded')
        previous=point
    for key in ('J2','J3','J4'):
        if abs(q[key]-taught['taught_joints'][key])>.5:raise TransferError('Endpoint joint winding differs from teaching')
    return q


def review(service,cfg,candidate):
    plan,taught=reference_for_candidate(candidate)
    if (FOLDER/('trial_'+candidate+'.json')).exists():raise TransferError('Approach already attempted; review evidence before retrying')
    s=preflight(service)
    n=DragGoRPC(service._endpoint_addr()[0]).info()
    if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):raise TransferError('Arm must be stationary in healthy Auto')
    if abs(n['external_axes']['E1']-28)>.15:raise TransferError('Open jaws to 28 mm at Home before this approach')
    if abs(n['external_axes']['E2']-taught['e2_degrees'])>.1:raise TransferError('Holder differs from the taught alignment angle')
    points=candidate_points(plan,candidate)
    validate_route(s['pose_mm'],points,s['joints'],cfg,service.envelope,candidate)
    return dict(candidate=candidate,start=s['pose_mm'],joints=s['joints'],points=points,
        e1=n['external_axes']['E1'],e2=n['external_axes']['E2'],plan_sha256=plan.get('profile_sha256',PLAN_SHA))


def execute(run,service,cfg,approved):
    from trajectory_queue import LuaTrajectory
    candidate=approved['candidate'];fresh=review(service,cfg,candidate)
    near(fresh['start'],approved['start'],.05)
    path=FOLDER/('trial_'+candidate+'.json')
    record=dict(status='started',plan=fresh,started_at=time.time(),samples=[],
        speed=137,gripper_commands=[],descend_beyond_alignment=candidate=='corrected02',
        authorization='Operator confirmed empty jaws, new route and open-jaw sweep clear, hands clear and E-stop supervised.')
    with path.open('x') as f:json.dump(record,f,indent=2)
    def save():path.write_text(json.dumps(record,indent=2))
    def monitor(stage,done,total):
        s=service.status();n=DragGoRPC(service._endpoint_addr()[0]).info()
        if run.stopped() or not s.get('ok') or s.get('errors') or any(n.get(k,True) for k in ('error','emergency','drag','manual')):
            raise TransferError('Approach stopped or controller feedback is unhealthy')
        if abs(n['external_axes']['E1']-28)>.15 or abs(n['external_axes']['E2']-fresh['e2'])>.1:
            raise TransferError('Jaw opening or holder angle changed during approach')
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=s,native=n));save()
    try:
        monitor('before_upload',0,1)
        record['queue_result']=LuaTrajectory(service).execute(run,fresh['start'],fresh['joints'],fresh['points'],cfg,137,monitor,reviewed=True,short_side_alignment=candidate)
        monitor('finished',1,1)
        final=service.status();near(final['pose_mm'],fresh['points'][-1],.2)
        record.update(status='completed_awaiting_operator_inspection',final_robot=final)
        return dict(ok=True,report=str(path),endpoint=final['pose_mm'],e1=final['external_axes']['E1'],queues=1,speed=137)
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error));raise
    finally:
        record['finished_at']=time.time();save()
