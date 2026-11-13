"""Offline revision 03: taught turn, level hover, fast descent then slow seating.

No hardware calls. The added clearance height is proposed, not collision-certified.
"""
import hashlib
import argparse
import json
import math
import time
from autonomy import TransferError
from short_side_direct_transfer import reference as parent_reference, validate_plan_route, PLAN as PARENT, SELECTION
from hamilton_short_side_trial import FOLDER, ROOT
from plan_short_side_hamilton import validate
from scope_step_trial import near
from trajectory_queue import checksum

PLAN=FOLDER/'hamilton_short_side_hover03_plan.json'
PLAN_SHA='65d3a7041e934f995b7323c09d707e5d8cb776bcdcd1019f12f3e355f243a402'
PLAN04=FOLDER/'hamilton_short_side_hover04_plan.json'
PLAN04_SHA='f360350e3bb2d16f182f47f15d8ce90439dfd762598f6a21910e532ae7de2968'
PROFILES=('pickup_hover03_forward','pickup_hover03_reverse','pickup_hover04_forward','pickup_hover04_reverse','pickup_hover04_departure')

def build():
    parent,site,grip=parent_reference()
    old=parent['routes']['forward'];start=old['start'];turn=parent['taught_turn']
    end=old['points'][-1]
    ready=dict(turn,Z=round(turn['Z']+20,2),Rz=end['Rz'])
    hover=dict(end,Z=ready['Z']);slow_start=dict(end,Z=55.0)
    forward=[turn,ready,hover,slow_start,end]
    reverse=list(reversed([start]+forward))[1:]
    speeds=[137,137,137,137,5]
    cfg=parent['config'];env={k:tuple(v) for k,v in parent['station_envelope'].items()}
    q=old['start_joints'];end_q=site['measured_endpoint_joints']
    routes={}
    for name,origin,points,joints,expected,velocity in (
        ('forward',start,forward,q,end_q,speeds),
        ('reverse',end,reverse,end_q,q,list(reversed(speeds)))):
        checked=validate(origin,points,joints,cfg,env,expected)
        if not checked['workspace_valid'] or not checked['ik_and_joint_limits_valid']:
            raise TransferError('Hover route failed offline validation')
        routes[name]=dict(start=origin,start_joints=joints,points=points,validation=checked,
            speed=137,segment_speeds=velocity,queues=1,move_l_commands=5,completion_barriers=1,
            payload=dict(header=[5,137,-1]+[origin[k] for k in ('X','Y','Z','Rz')]+[joints[k] for k in ('J1','J2','J3','J4')],
                         points=points,segment_speeds=velocity,checksum=checksum(points,velocity)))
    return dict(revision='03',created_at=time.time(),status='offline_valid_pending_supervised_trial',
        parent_file=PARENT.name,parent_sha256=hashlib.sha256(PARENT.read_bytes()).hexdigest(),
        config=cfg,global_envelope=parent['global_envelope'],station_envelope=env,
        taught_turn=turn,entry_ready=ready,site_hover=hover,slow_descent_start=slow_start,
        routes=routes,pickup_settings=grip,reference_hashes=parent['reference_hashes'],
        workflow=['open_at_home','accepted_approach_descent','close_to_25','lift_5_at_5','pickup_to_hamilton_via_hover03'],
        home_between_pickup_and_hamilton=False,global_limits_changed=False,
        hardware_tested=False,collision_clearance_verified=False,execution_enabled=False,
        reasoning='Keep the taught turning point; combine remaining wrist turn with a 20 mm rise, cross level above site 4, descend vertically at 137 to Z55, then at 5 to the unchanged taught Z52.03 endpoint.',
        prior_trial='Revision 02 reached the endpoint but its jaw-position monitor stopped the program; normal completion and physical retention were not verified.',
        limitation='The extra 20 mm rise and hover sweep are untested. IK validates reach and joints, not obstacle or payload clearance. Commanded speed does not guarantee actual speed or continuous blending.')

def reference(revision='03'):
    if revision=='04':
        parent,site,grip=reference('03')
        raw=PLAN04.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=PLAN04_SHA:raise TransferError('Corrected endpoint route changed')
        p=json.loads(raw)
        if p['parent_sha256']!=PLAN_SHA:raise TransferError('Corrected endpoint parent changed')
        if hashlib.sha256((FOLDER/p['taught_endpoint_file']).read_bytes()).hexdigest()!=p['taught_endpoint_sha256']:
            raise TransferError('Corrected endpoint teaching changed')
        # Exact reversed entry, stopping at the taught clearance turn instead
        # of continuing back down to the pickup holder with the plate.
        reverse=p['routes']['reverse'];points=reverse['points'][:-1]
        expected=[s['joints'] for s in p['routes']['forward']['validation']['dense_samples'] if s['segment']==0][-1]
        checked=validate(reverse['start'],points,reverse['start_joints'],p['config'],p['station_envelope'],expected)
        if not checked['workspace_valid']:raise TransferError('Departure outside station workspace')
        p['routes']['departure']=dict(start=reverse['start'],start_joints=reverse['start_joints'],
            points=points,segment_speeds=reverse['segment_speeds'][:-1],validation=checked,
            queues=1,move_l_commands=4,completion_barriers=1)
        return p,site,grip
    if revision!='03':raise TransferError('Unknown hover revision')
    raw=PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PLAN_SHA:raise TransferError('Pinned hover route changed')
    p=json.loads(raw);_,site,grip=parent_reference()
    if hashlib.sha256(PARENT.read_bytes()).hexdigest()!=p['parent_sha256']:raise TransferError('Hover parent changed')
    return p,site,grip

def validate_shape(start,points,profile):
    if profile not in PROFILES:raise TransferError('Unknown Hamilton hover route')
    p,_,_=reference('04' if profile.startswith('pickup_hover04_') else '03');route=p['routes'][profile.split('_')[-1]]
    near(start,route['start'],.1)
    if points!=route['points']:raise TransferError('Hover route must retain turn, overhead crossing and both vertical descent points')
    return route

def validate_speeds(start,points,profile,speeds):
    if profile in ('cellvis24_recorded_forward','cellvis24_recorded_reverse','cellvis24_smoothed_forward','cellvis24_smoothed_reverse','cellvis24_opposite_forward','cellvis24_opposite_reverse'):
        from cellvis24_recorded_hamilton_route import validate_speeds as recorded
        return recorded(start,points,profile,speeds)
    if profile in ('cellvis24_taught_three_forward','cellvis24_taught_three_reverse'):
        from cellvis24_taught_three_route import validate_speeds as taught
        return taught(start,points,profile,speeds)
    if profile in ('cellvis24_direct_forward','cellvis24_direct_reverse'):
        from cellvis24_direct_rack import validate_speeds as direct_rack
        return direct_rack(start,points,profile,speeds)
    if profile in ('cellvis24_rack_forward','cellvis24_rack_reverse'):
        from cellvis24_rack_route import validate_speeds as loaded_rack
        return loaded_rack(start,points,profile,speeds)
    if profile in ('empty_rack03_idle','empty_rack03_hamilton','empty_rack04_home','empty_rack04_hamilton','empty_original40_home','empty_original40_hamilton','empty_turn05_home','empty_turn05_hamilton','empty_rack06_home','empty_rack06_hamilton','empty_rack07_home','empty_rack07_hamilton'):
        from hamilton_rack_clearance import validate_speeds as rack
        return rack(start,points,profile,speeds)
    if profile=='empty_home_hamilton40':
        from hamilton_empty_clearance import validate_speeds as empty
        return empty(start,points,profile,speeds)
    if profile in ('cellvis24_hamilton_forward','cellvis24_hamilton_reverse'):
        from cellvis24_hamilton_route import validate_speeds as cellvis
        return cellvis(start,points,profile,speeds)
    route=validate_shape(start,points,profile)
    if speeds is None or list(speeds)!=route['segment_speeds'] or any(type(v) not in (int,float) or not math.isfinite(v) for v in speeds):
        raise TransferError('Hover route requires speed 137 to Z55 and speed 5 only for final seating (reversed on departure)')

def validate_route(start,points,joints,cfg,envelope,profile):
    p,_,_=reference('04' if profile.startswith('pickup_hover04_') else '03');route=validate_shape(start,points,profile)
    return validate_plan_route(p,route,start,points,joints,cfg,envelope)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--select',action='store_true',help='Save offline candidate selection and append observations; no hardware')
    if parser.parse_args().select:
        select_candidate()
        return
    if PLAN.exists():raise RuntimeError('Preserve existing revision; do not overwrite')
    p=build()
    with PLAN.open('x') as f:json.dump(p,f,indent=2)
    print(json.dumps(dict(plan=str(PLAN),sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        points=p['routes']['forward']['points'],speeds=p['routes']['forward']['segment_speeds'],
        length_mm=p['routes']['forward']['validation']['length_mm']),indent=2))

def select_candidate():
    p,_,_=reference()
    prior=SELECTION.read_bytes();previous=json.loads(prior)
    archive=FOLDER/'route_selection02_before_hover03.json'
    if previous['revision']=='02':
        if archive.exists() and archive.read_bytes()!=prior:raise RuntimeError('Selection archive differs')
        if not archive.exists():
            with archive.open('xb') as f:f.write(prior)
    elif previous['revision']!='03' or previous['plan_sha256']!=PLAN_SHA:
        raise RuntimeError('Another candidate was selected; do not replace it')
    selection=dict(revision='03',plan_path=str(PLAN.relative_to(ROOT.parent)),plan_sha256=PLAN_SHA,
        status='offline_valid_pending_supervised_trial',segment_speeds=p['routes']['forward']['segment_speeds'],
        slow_descent_starts_at_z_mm=55.0,placement_z_mm=52.03,
        home_between_pickup_and_hamilton=False,execution_enabled=False)
    SELECTION.write_text(json.dumps(selection,indent=2),encoding='utf-8')
    observations=ROOT/'reports/trajectory_smoothing/Observations.md'
    note='''

### 2026-11-10 - Hamilton overhead approach, offline revision 03
- Operator reported slow turning and requested overhead entry instead of diagonal descent. Revision02 telemetry shows about 5 seconds on the stationary wrist turn despite commanded speed137; subsequent diagonal transit reached about 130-139 mm/s. This identifies the slow phase, not the controller's internal cause.
- Preserve taught turn X312.57/Y-43.52/Z117.93/Rz-56.32. Combine remaining yaw to -93.56 with a proposed 20 mm rise, cross level to X374.04/Y-184.17/Z137.93, then descend vertically. No Home detour after pickup.
- Operator corrected the speed transition: descend at137 to Z55, then at5 for the final 2.97 mm to unchanged taught Z52.03 placement. Five MoveL points in one queue, speeds [137,137,137,137,5]; reverse geometry uses reversed speeds. Accepted pickup/opening/grip25/proof-lift settings unchanged.
- Dense IK and joint/workspace checks pass both directions; global Z70 minimum unchanged. New hover height and swept clearance are NOT physically validated. Commanded speed does not guarantee actual velocity or blending at corners.
- 58 focused offline tests pass: new geometry, published Lua220109 with fake hardware, five commands/one completion barrier, exact speed mask, external-axis preservation, interrupted-upload Stop, and existing Hamilton/Squid queues. No hardware movement, restart, fault reset, backend reload or new publication performed.
- Saved holder_short_side/alignment/hamilton_short_side_hover03_plan.json, archived revision02 selection, and selected revision03 as the next offline trial candidate. Developer trial03 and runner --revision 03 are prepared on disk, not activated in the running backend. Earlier successes and failed/uncertain trials retained. Pending supervised clearance and physical acceptance.
'''
    # Preserve the historical file's mixed encoding byte-for-byte.
    if b'### 2026-11-10 - Hamilton overhead approach, offline revision 03' not in observations.read_bytes():
        with observations.open('ab') as f:f.write(note.encode('ascii'))
    print('Offline candidate selected and observations appended. No hardware access.')

if __name__=='__main__':main()
