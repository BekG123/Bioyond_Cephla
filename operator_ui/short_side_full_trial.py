"""Pinned pickup approach and loaded Hamilton transfer for full trial 01."""
import hashlib
import json
import time
from autonomy import TransferError,check_path
from draggo import DragGoRPC
from scope_step_trial import preflight,near
from hamilton_short_side_trial import FOLDER,ROOT,reference as original_reference
from short_side_alignment_trial import reference_for_candidate,candidate_points,validate_route as validate_pickup

PLAN_SHA='a98793b0b132cd3a6a006899b1cf0e7eeB981c2de6df82650d8ff013d42350b9'.lower()
GRIP_SHA='13ac01f0c360589f3e40dfb5a0bbdc4098b395b845d35ec652f8f5ad3385b99e'

def reference(revision='01'):
    if revision in ('03','04'):
        from short_side_hover_transfer import reference as hover
        return hover(revision)
    if revision=='02':
        from short_side_direct_transfer import reference as direct
        return direct()
    if revision!='01':raise TransferError('Unknown full trial revision')
    _,parent=original_reference()
    raw=(FOLDER/'hamilton_short_side_via_turning01_plan.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PLAN_SHA:raise TransferError('Revised Hamilton route changed')
    p=json.loads(raw)
    if hashlib.sha256((FOLDER/'taught_hamilton_short_side_turning01.json').read_bytes()).hexdigest()!=p['taught_waypoint_sha256']:
        raise TransferError('Turning waypoint changed')
    raw=(ROOT.parent/'Pick and Hold/Grip/short_side_48well_reference.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=GRIP_SHA:raise TransferError('Accepted grip reference changed')
    return p,parent,json.loads(raw)['settings']

def validate_shape(start,points,profile):
    p,_,_=reference()
    if profile not in ('turning01_forward','turning01_reverse'):raise TransferError('Unknown turning route')
    direction=profile.split('_')[-1];route=p['routes'][direction]
    near(start,route['start'],.1)
    if points!=route['points']:raise TransferError('Revised Hamilton route or waypoint changed')

def validate_route(start,points,joints,cfg,envelope,profile):
    p,parent,_=reference();validate_shape(start,points,profile)
    if cfg!=p['config']:raise TransferError('Revised Hamilton configuration changed')
    env={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
    if {k:tuple(v) for k,v in envelope.items()}!=env:raise TransferError('Workspace changed')
    direction=profile.split('_')[-1];route=p['routes'][direction]
    for k in ('J1','J2','J3','J4'):
        if abs(joints[k]-route['start_joints'][k])>.5:raise TransferError('Starting joints changed')
    env={k:tuple(v) for k,v in p['station_envelope'].items()}
    q=dict(joints);previous=start;offset=q['J1']-start['Z']
    taught=json.loads((FOLDER/'taught_hamilton_short_side_turning01.json').read_bytes())['joints']
    for index,point in enumerate(points):
        q=check_path(previous,point,q,cfg,env);q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Joint travel exceeded')
        expected=taught if index==0 else parent['measured_endpoint_joints' if direction=='forward' else 'home_joints']
        if any(abs(q[k]-expected[k])>.5 for k in ('J1','J2','J3','J4')):raise TransferError('Joint winding differs from teaching')
        previous=point
    return q

def receipt(phase,revision='01',attempt=''):
    if revision not in ('01','02','03','04'):raise TransferError('Unknown full trial revision')
    if attempt not in ('','retry01','retry02','retry03') or (attempt and revision!='03'):raise TransferError('Unknown trial attempt')
    return FOLDER/('full_sequence'+revision+('_'+attempt if attempt else '')+'_'+phase+'.json')

def review(service,cfg,phase,revision='01',attempt=''):
    p,_,grip=reference(revision)
    if phase not in ('approach','hamilton','departure') or (phase=='departure' and revision!='04'):raise TransferError('Unknown trial phase')
    if receipt(phase,revision,attempt).exists():raise TransferError('Trial phase already attempted; inspect evidence before retry')
    if attempt or revision=='04':
        prep=json.loads(receipt('ready',revision,attempt).read_bytes())
        if prep['status']!='completed' or not prep['operator_confirmed_plate_reseated_empty_jaws']:
            raise TransferError('Retry requires recorded empty-gripper recovery and Home completion')
    s=preflight(service);n=DragGoRPC(service._endpoint_addr()[0]).info()
    if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):raise TransferError('Healthy stationary Auto required')
    expected_e1=28 if phase=='approach' else 25
    if abs(n['external_axes']['E1']-expected_e1)>.07 or (phase=='approach' and abs(n['external_axes']['E2']-grip['holder_e2_degrees'])>.1):
        raise TransferError('Jaw or holder position differs from accepted setup')
    if phase=='approach':
        plan,_=reference_for_candidate('corrected02');points=candidate_points(plan,'corrected02')
        validate_pickup(s['pose_mm'],points,s['joints'],cfg,service.envelope,'corrected02')
    else:
        proof=json.loads(receipt('grip_lift',revision,attempt).read_bytes())
        if proof['status']!='completed':raise TransferError('Pickup/lift did not complete')
        direction='departure' if phase=='departure' else 'forward'
        if phase=='departure':
            accepted=json.loads(receipt('operator_acceptance','04').read_bytes())
            raw=receipt('hamilton','04').read_bytes()
            if accepted.get('accepted') is not True or accepted['hamilton_sha256']!=hashlib.sha256(raw).hexdigest() or json.loads(raw)['status']!='completed':
                raise TransferError('Departure requires operator-accepted completed placement')
        points=p['routes'][direction]['points']
        if revision in ('03','04'):
            from short_side_hover_transfer import validate_route as hover
            hover(s['pose_mm'],points,s['joints'],cfg,service.envelope,'pickup_hover'+revision+'_'+direction)
        elif revision=='02':
            from short_side_direct_transfer import validate_route as direct
            direct(s['pose_mm'],points,s['joints'],cfg,service.envelope,'pickup_turning02_forward')
        else:validate_route(s['pose_mm'],points,s['joints'],cfg,service.envelope,'turning01_forward')
    route_sha=hashlib.sha256((FOLDER/'hamilton_short_side_pickup_direct02_plan.json').read_bytes()).hexdigest() if revision=='02' else PLAN_SHA
    if revision=='03':
        from short_side_hover_transfer import PLAN_SHA as hover_sha
        route_sha=hover_sha
    if revision=='04':
        from short_side_hover_transfer import PLAN04_SHA
        route_sha=PLAN04_SHA
    return dict(phase=phase,revision=revision,attempt=attempt,start=s['pose_mm'],joints=s['joints'],points=points,e1=expected_e1,e2=n['external_axes']['E2'],plan_sha256=route_sha,
                segment_speeds=p['routes']['departure' if phase=='departure' else 'forward']['segment_speeds'] if revision in ('03','04') and phase!='approach' else None)

def execute(run,service,cfg,approved):
    from trajectory_queue import LuaTrajectory
    phase=approved['phase'];revision=approved.get('revision','01');attempt=approved.get('attempt','');fresh=review(service,cfg,phase,revision,attempt);near(fresh['start'],approved['start'],.05)
    if fresh['plan_sha256']!=approved['plan_sha256']:raise TransferError('Plan changed before dispatch')
    path=receipt(phase,revision,attempt);record=dict(status='started',started_at=time.time(),plan=fresh,samples=[],speed=137,
        authorization='Operator confirmed empty jaws, plate in rotated holder, all Home/pickup/revised Hamilton routes clear; hands clear and E-stop supervised.',
        plate_retention_observation='pending',gripper_commands=[])
    with path.open('x') as f:json.dump(record,f,indent=2)
    def save():path.write_text(json.dumps(record,indent=2))
    def monitor(stage,done,total):
        s=service.status();n=DragGoRPC(service._endpoint_addr()[0]).info()
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=s,native=n));save()
        if run.stopped() or not s.get('ok') or s.get('errors') or any(n.get(k,True) for k in ('error','emergency','drag','manual')):
            raise TransferError('Trial stopped or unhealthy feedback')
        if abs(n['external_axes']['E1']-fresh['e1'])>.07 or (phase=='approach' and abs(n['external_axes']['E2']-fresh['e2'])>.1):raise TransferError('Jaw or pickup-holder position changed')
    try:
        monitor('before_upload',0,1)
        flags=dict(short_side_alignment='corrected02') if phase=='approach' else dict(hamilton_short_side='pickup_turning02_forward' if revision=='02' else 'turning01_forward')
        if phase!='approach' and revision in ('03','04'):
            flags=dict(hamilton_short_side='pickup_hover'+revision+('_departure' if phase=='departure' else '_forward'),segment_speeds=fresh['segment_speeds'])
        record['queue_result']=LuaTrajectory(service).execute(run,fresh['start'],fresh['joints'],fresh['points'],cfg,137,monitor,reviewed=True,**flags)
        monitor('finished',1,1);final=service.status();near(final['pose_mm'],fresh['points'][-1],.2)
        record.update(status='completed',final_robot=final)
        return dict(ok=True,report=str(path),endpoint=final['pose_mm'],queues=1,speed=137)
    except Exception as e:record.update(status='failed_or_uncertain',error=str(e));raise
    finally:record['finished_at']=time.time();save()
