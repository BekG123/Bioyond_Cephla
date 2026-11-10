"""One-shot, pinned empty-gripper site-4/Home trials; no station release."""
import hashlib
import json
import time
from pathlib import Path
from autonomy import TransferError, check_path
from draggo import DragGoRPC
from scope_step_trial import near, preflight

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'reports/holder_short_side/alignment'
PLAN_SHA='a534146ab48f890d08ed7547a3ced36016d24a02fd78353858e0e2f87ad8cd98'

def reference():
    raw=(FOLDER/'hamilton_short_side_station_plan.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PLAN_SHA:raise TransferError('Hamilton station plan changed')
    p=json.loads(raw);parent_raw=(FOLDER/p['parent_file']).read_bytes()
    if hashlib.sha256(parent_raw).hexdigest()!=p['parent_sha256']:raise TransferError('Hamilton parent plan changed')
    parent=json.loads(parent_raw)
    for path,expected in [(ROOT/'points.json',parent['home_sha256']),
                          (FOLDER/'taught_hamilton_site4_short_side.json',parent['taught_sha256'])]:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise TransferError('Hamilton teaching or Home changed')
    return p,parent

def validate_shape(start,points,direction):
    if direction in ('pickup_hover03_forward','pickup_hover03_reverse','pickup_hover04_forward','pickup_hover04_reverse','pickup_hover04_departure'):
        from short_side_hover_transfer import validate_shape as hover
        return hover(start,points,direction)
    if direction in ('pickup_turning02_forward','pickup_turning02_reverse'):
        from short_side_direct_transfer import validate_shape as direct
        return direct(start,points,direction)
    if direction in ('turning01_forward','turning01_reverse'):
        from short_side_full_trial import validate_shape as revised
        return revised(start,points,direction)
    p,_=reference()
    if direction not in ('reverse','forward'):raise TransferError('Unknown Hamilton trial direction')
    route=p['routes'][direction]
    near(start,route['start'],.5)
    if points!=route['points']:raise TransferError('Hamilton queue differs from approved direct route')

def validate_route(start,points,joints,cfg,envelope,direction):
    if direction in ('pickup_hover03_forward','pickup_hover03_reverse','pickup_hover04_forward','pickup_hover04_reverse','pickup_hover04_departure'):
        from short_side_hover_transfer import validate_route as hover
        return hover(start,points,joints,cfg,envelope,direction)
    if direction in ('pickup_turning02_forward','pickup_turning02_reverse'):
        from short_side_direct_transfer import validate_route as direct
        return direct(start,points,joints,cfg,envelope,direction)
    if direction in ('turning01_forward','turning01_reverse'):
        from short_side_full_trial import validate_route as revised
        return revised(start,points,joints,cfg,envelope,direction)
    p,parent=reference();validate_shape(start,points,direction)
    if cfg!=p['config']:raise TransferError('Hamilton IK configuration changed')
    expected_env={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
    if {k:tuple(v) for k,v in envelope.items()}!=expected_env:raise TransferError('Global workspace changed')
    source=parent['home_joints' if direction=='forward' else 'measured_endpoint_joints']
    target=parent['measured_endpoint_joints' if direction=='forward' else 'home_joints']
    for k in ('J1','J2','J3','J4'):
        if abs(joints[k]-source[k])>.5:raise TransferError('Hamilton start joint winding changed: '+k)
    env={k:tuple(v) for k,v in p['station_envelope'].items()}
    # Only absorb sub-0.01 mm feedback rounding at the exact taught station.
    if direction=='reverse' and env['Z'][0]-.01<=start['Z']<env['Z'][0]:
        env['Z']=(start['Z'],env['Z'][1])
    q=dict(joints);previous=start;offset=joints['J1']-start['Z']
    for point in points:
        q=check_path(previous,point,q,cfg,env);q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Hamilton joint travel exceeded')
        previous=point
    for k in ('J1','J2','J3','J4'):
        if abs(q[k]-target[k])>.5:raise TransferError('Hamilton terminal joint winding differs: '+k)
    return q

def receipt(direction):return FOLDER/('hamilton_short_side_'+direction+'_trial01.json')

def review(service,cfg,direction):
    p,_=reference()
    if direction not in ('reverse','forward'):raise TransferError('Unknown trial direction')
    if receipt(direction).exists():raise TransferError('Trial already attempted; review its record before retry')
    if direction=='forward':
        reverse=json.loads(receipt('reverse').read_bytes())
        if reverse['status']!='completed_awaiting_operator_inspection' or reverse['plan']['plan_sha256']!=PLAN_SHA:
            raise TransferError('Reverse trial has no verified completion')
    s=preflight(service);n=DragGoRPC(service._endpoint_addr()[0]).info()
    if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):raise TransferError('Healthy stationary Auto required')
    if abs(n['external_axes']['E1'])>.15:raise TransferError('Empty startup jaw position expected')
    points=p['routes'][direction]['points']
    validate_route(s['pose_mm'],points,s['joints'],cfg,service.envelope,direction)
    return dict(direction=direction,start=s['pose_mm'],joints=s['joints'],points=points,
                e1=n['external_axes']['E1'],e2=n['external_axes']['E2'],plan_sha256=PLAN_SHA)

def execute(run,service,cfg,approved):
    from trajectory_queue import LuaTrajectory
    direction=approved['direction'];fresh=review(service,cfg,direction)
    near(fresh['start'],approved['start'],.05)
    if abs(fresh['e1']-approved['e1'])>.1 or abs(fresh['e2']-approved['e2'])>.1:raise TransferError('External axes changed before dispatch')
    path=receipt(direction)
    record=dict(status='started',started_at=time.time(),plan=fresh,samples=[],speed=137,
                gripper_commands=[],payload='empty',
                authorization='Operator confirmed both direct routes and full sweep clear; plate removed; jaws empty; hands clear; E-stop supervised.')
    with path.open('x') as f:json.dump(record,f,indent=2)
    def save():path.write_text(json.dumps(record,indent=2))
    def monitor(stage,done,total):
        s=service.status();n=DragGoRPC(service._endpoint_addr()[0]).info()
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=s,native=n));save()
        if run.stopped() or not s.get('ok') or s.get('errors') or any(n.get(k,True) for k in ('error','emergency','drag','manual')):
            raise TransferError('Hamilton trial stopped or unhealthy feedback')
        if abs(n['external_axes']['E1']-fresh['e1'])>.15 or abs(n['external_axes']['E2']-fresh['e2'])>.1:
            raise TransferError('Jaw or holder position changed during travel')
    try:
        monitor('before_upload',0,1)
        record['queue_result']=LuaTrajectory(service).execute(run,fresh['start'],fresh['joints'],fresh['points'],cfg,137,monitor,reviewed=True,hamilton_short_side=direction)
        monitor('finished',1,1);final=service.status();near(final['pose_mm'],fresh['points'][-1],.2)
        record.update(status='completed_awaiting_operator_inspection',final_robot=final)
        return dict(ok=True,report=str(path),endpoint=final['pose_mm'],queues=1,speed=137)
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error));raise
    finally:
        record['finished_at']=time.time();save()
