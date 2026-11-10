"""Revision 02: pickup -> taught turning point -> Hamilton, without Home."""
import hashlib
import json
import time
from autonomy import TransferError,check_path
from hamilton_short_side_trial import FOLDER,ROOT,reference as original_reference
from plan_short_side_hamilton import validate
from plan_hamilton_turning_waypoint import quantize
from scope_step_trial import near
from trajectory_queue import checksum

PLAN=FOLDER/'hamilton_short_side_pickup_direct02_plan.json'
SELECTION=ROOT.parent/'Pick and Hold/short_side_hamilton_route.json'
PLAN_SHA='d849bdc949b975848c33e9279b31ead2df38f35f89f70efde942e0ac4c7abf84'

def build():
    station,parent=original_reference()
    raw=(FOLDER/'taught_hamilton_short_side_turning02.json').read_bytes();taught=json.loads(raw)
    grip_raw=(ROOT.parent/'Pick and Hold/Grip/short_side_48well_reference.json').read_bytes();grip=json.loads(grip_raw)['settings']
    lift_raw=(FOLDER/'full_sequence01_grip_lift.json').read_bytes();lift=json.loads(lift_raw)
    if lift['status']!='completed':raise TransferError('No completed short-side lift reference')
    if taught['config']!=station['config'] or taught['envelope']!=station['global_envelope']:raise TransferError('Teaching configuration changed')
    start=quantize(grip['proof_lift_endpoint']);site=quantize(parent['taught_endpoint']);turn=quantize(taught['target'])
    ready=dict(turn,Rz=site['Rz']);q=lift['final_state']['robot']['joints']
    near(lift['final_state']['robot']['pose_mm'],start,.05)
    cfg=station['config'];env={k:tuple(v) for k,v in station['station_envelope'].items()}
    # Complete yaw at the taught clearance location, before descending into site 4.
    forward_points=[turn,ready,site];reverse_points=[ready,turn,start]
    forward=validate(start,forward_points,q,cfg,env,parent['measured_endpoint_joints'])
    reverse=validate(site,reverse_points,parent['measured_endpoint_joints'],cfg,env,q)
    branch=validate(start,[turn],q,cfg,env,taught['joints'])
    if not all(v['workspace_valid'] for v in (forward,reverse,branch)):raise TransferError('Revised route outside station workspace')
    routes={}
    for name,origin,points,joints,validation in (
        ('forward',start,forward_points,q,forward),('reverse',site,reverse_points,parent['measured_endpoint_joints'],reverse)):
        routes[name]=dict(start=origin,start_joints=joints,points=points,validation=validation,
            speed=137,queues=1,move_l_commands=3,completion_barriers=1,
            payload=dict(header=[3,137,-1]+[origin[k] for k in ('X','Y','Z','Rz')]+[joints[k] for k in ('J1','J2','J3','J4')],
                         checksum=checksum(points),points=points))
    return dict(revision='02',status='offline_valid_pending_supervised_trial',created_at=time.time(),
        taught_turn=turn,entry_ready=ready,taught_joint_branch_validation=branch,
        config=cfg,global_envelope=station['global_envelope'],station_envelope=env,
        routes=routes,pickup_settings=grip,
        workflow=['open_at_home','accepted_approach_descent','close_to_25','lift_5_at_5','pickup_to_hamilton_via_turning02'],
        home_between_pickup_and_hamilton=False,
        reference_hashes=dict(teaching=hashlib.sha256(raw).hexdigest(),grip=hashlib.sha256(grip_raw).hexdigest(),lift=hashlib.sha256(lift_raw).hexdigest(),home=parent['home_sha256'],site=parent['taught_sha256']),
        global_limits_changed=False,hardware_tested=False,collision_clearance_verified=False,execution_enabled=False,
        reasoning='Complete the wrist turn at the newly taught clearance point, then hold yaw fixed through Hamilton entry. Do not route a picked-up plate through Home.',
        limitation='IK is not a collision model. Swept clearance from pickup and at the turning position, and the fixed-yaw entry segment, require a new supervised trial.',
        prior_failed_trials_preserved=True)

def reference():
    raw=PLAN.read_bytes()
    if PLAN_SHA!=hashlib.sha256(raw).hexdigest():raise TransferError('Pinned direct route changed')
    p=json.loads(raw);_,parent=original_reference()
    sources={'teaching':FOLDER/'taught_hamilton_short_side_turning02.json',
             'grip':ROOT.parent/'Pick and Hold/Grip/short_side_48well_reference.json',
             'lift':FOLDER/'full_sequence01_grip_lift.json','home':ROOT/'points.json',
             'site':FOLDER/'taught_hamilton_site4_short_side.json'}
    for name,path in sources.items():
        if hashlib.sha256(path.read_bytes()).hexdigest()!=p['reference_hashes'][name]:raise TransferError('Direct-route reference changed: '+name)
    return p,parent,p['pickup_settings']

def validate_shape(start,points,profile):
    p,_,_=reference()
    if profile not in ('pickup_turning02_forward','pickup_turning02_reverse'):raise TransferError('Unknown direct pickup route')
    route=p['routes'][profile.split('_')[-1]];near(start,route['start'],.1)
    if points!=route['points']:raise TransferError('Direct route must retain its turning and fixed-yaw entry points')

def validate_route(start,points,joints,cfg,envelope,profile):
    p,_,_=reference();validate_shape(start,points,profile);direction=profile.split('_')[-1];route=p['routes'][direction]
    return validate_plan_route(p,route,start,points,joints,cfg,envelope)

def validate_plan_route(p,route,start,points,joints,cfg,envelope):
    if cfg!=p['config']:raise TransferError('Direct-route IK configuration changed')
    env={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
    if {k:tuple(v) for k,v in envelope.items()}!=env:raise TransferError('Global workspace changed')
    if any(abs(joints[k]-route['start_joints'][k])>.5 for k in ('J1','J2','J3','J4')):raise TransferError('Direct-route starting joint winding differs')
    env={k:tuple(v) for k,v in p['station_envelope'].items()};q=dict(joints);previous=start;offset=joints['J1']-start['Z']
    for point in points:
        q=check_path(previous,point,q,cfg,env);q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Joint travel exceeded')
        previous=point
    expected=route['validation']['endpoint_joints']
    if any(abs(q[k]-expected[k])>.5 for k in ('J1','J2','J3','J4')):raise TransferError('Terminal joint winding differs')
    return q

def main():
    if PLAN.exists() or SELECTION.exists():raise RuntimeError('Revision or selection already exists; preserve before changing')
    p=build()
    with PLAN.open('x') as f:json.dump(p,f,indent=2)
    selection=dict(revision='02',plan_path=str(PLAN.relative_to(ROOT.parent)),plan_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
                   status='prepared_pending_supervised_trial',home_between_pickup_and_hamilton=False,execution_enabled=False)
    with SELECTION.open('x') as f:json.dump(selection,f,indent=2)
    print(json.dumps(dict(plan=str(PLAN),selection=str(SELECTION),turn=p['taught_turn'],entry_ready=p['entry_ready'],
                         route=p['routes']['forward']['points'],length_mm=p['routes']['forward']['validation']['length_mm'],speed=137),indent=2))

if __name__=='__main__':main()
