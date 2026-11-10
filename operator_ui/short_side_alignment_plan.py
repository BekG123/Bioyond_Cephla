"""Capture a taught open-jaw waypoint and plan Home travel. No motion commands."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
from autonomy import check_path, wrap
from draggo import DragGoRPC
from proof_lift_plate import api, near
from trajectory_queue import prepare_points, checksum

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reports/holder_short_side/alignment'
KEYS=('X','Y','Z','Rz')


def home_reference():
    raw=(ROOT/'points.json').read_bytes()
    h=json.loads(raw)['points']['Home']
    return dict(X=h['x'],Y=h['y'],Z=h['z_grip'],Rz=h['rz']),h['joint_reference'],hashlib.sha256(raw).hexdigest()


def capture(confirmed=False):
    if not confirmed:raise ValueError('Operator must say the ideal alignment waypoint is positioned and stopped.')
    path=OUT/'taught_alignment.json'
    if path.exists():raise ValueError('A target is already saved; preserve it before teaching a replacement.')
    home,_,_=home_reference()
    rotation_raw=(ROOT/'reports/holder_short_side/fast_quarter_turn.json').read_bytes()
    rotation=json.loads(rotation_raw)
    if rotation['status']!='fast_quarter_turn_completed':raise ValueError('Holder rotation has no completed reference')
    expected_e2=rotation['target_degrees']
    s=api('state')
    if s['sequence']['active']:raise ValueError('An operation is active')
    if not s['robot'].get('connected'):
        if not api('connect',{'ip':'192.168.201.220'}).get('ok'):raise ValueError('Connect failed')
    samples=[]
    for _ in range(3):
        s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
        if (s['sequence']['active'] or not r.get('ok') or not r.get('connected')
                or r.get('errors') or any(n[k] for k in ('moving','error','emergency'))):
            raise ValueError('Capture needs a stopped, fault-free arm')
        actual_e2=n['external_axes'].get('E2')
        if n.get('external_units',{}).get('E2')!='degrees' or not isinstance(actual_e2,(int,float)) or not math.isfinite(actual_e2):
            raise ValueError('Fresh E2 angular feedback required to save the taught setup')
        if samples:
            near(r['pose_mm'],samples[0]['robot']['pose_mm'],.1)
            if abs(actual_e2-samples[0]['native']['external_axes']['E2'])>.1:
                raise ValueError('Holder is not stable while capturing the taught setup')
        samples.append(dict(robot=r,native=n,at=time.time()))
        time.sleep(.2)
    target={k:samples[-1]['robot']['pose_mm'][k] for k in KEYS}
    if math.dist([target[k] for k in KEYS[:3]],[home[k] for k in KEYS[:3]])<5:
        raise ValueError('Arm remains near Home; do not save Home as the pickup alignment waypoint')
    record=dict(role='open_jaw_alignment_before_further_descent',target=target,
        taught_joints=samples[-1]['robot']['joints'],e2_degrees=samples[-1]['native']['external_axes']['E2'],
        earlier_rotation_e2_degrees=expected_e2,
        holder_changed_since_rotation=abs(samples[-1]['native']['external_axes']['E2']-expected_e2)>.1,
        required_travel_e1_mm=28,grip_z_mm=None,grip_e1_mm=None,
        descent_authorized=False,grip_authorized=False,travel_speed=137,
        executor='one_lua_queue',hardware_route_tested=False,
        holder_rotation_sha256=hashlib.sha256(rotation_raw).hexdigest(),samples=samples,
        config=api('robot_params'),envelope=s['envelope'],saved_at=time.time())
    OUT.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(record,f,indent=2,allow_nan=False)
    return record


def validate_candidate(home,home_joints,vertices,cfg,envelope,taught_joints):
    # Only subdivide straight legs; no inserted bends or additional stop requests.
    points=[];previous=home
    for end in vertices:
        end={**end,'Rz':previous['Rz']+wrap(end['Rz']-previous['Rz'])}
        length=math.dist([previous[k] for k in KEYS[:3]],[end[k] for k in KEYS[:3]])
        yaw=end['Rz']-previous['Rz']
        if length<.005 and abs(yaw)<.005:continue
        count=max(1,math.ceil(length/50),math.ceil(abs(yaw)/10))
        points.extend({k:previous[k]+(end[k]-previous[k])*i/count for k in KEYS} for i in range(1,count+1))
        previous=end
    points,_=prepare_points(home,home_joints,points,cfg,reviewed=True)
    previous=home;q=dict(home_joints);offset=q['J1']-home['Z'];length=0;samples=0
    limits={k:[q[k],q[k]] for k in ('J1','J2','J3','J4')}
    for end in points:
        distance=math.dist([previous[k] for k in KEYS[:3]],[end[k] for k in KEYS[:3]])
        count=max(1,math.ceil(distance),math.ceil(abs(end['Rz']-previous['Rz'])/.5))
        leg=previous
        for i in range(1,count+1):
            p={k:leg[k]+(end[k]-leg[k])*i/count for k in KEYS}
            q=check_path(previous,p,q,cfg,envelope);q['J1']=p['Z']+offset
            if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise ValueError('Path exceeds joint travel')
            for key,value in limits.items():value[0]=min(value[0],q[key]);value[1]=max(value[1],q[key])
            previous=p;samples+=1
        length+=distance
    for key in ('J2','J3','J4'):
        if abs(q[key]-taught_joints[key])>.5:raise ValueError('Route would arrive in a different joint configuration than the taught waypoint')
    return dict(points=points,queue_checksum=checksum(points),path_length_mm=length,
        dense_samples=samples,joint_ranges=limits,endpoint_joints=q,
        queued_waypoints=len(points),execution_queues=1,speed=137,
        collision_clearance_verified=False,hardware_tested=False)


def plan():
    path=OUT/'plan.json'
    if path.exists():raise ValueError('Plan exists; preserve the candidate before revising')
    raw=(OUT/'taught_alignment.json').read_bytes();taught=json.loads(raw)
    home,q,home_sha=home_reference();goal=taught['target']
    if not taught['envelope']['enabled']:raise ValueError('Workspace checks must remain enabled')
    env={k:(taught['envelope'][k]['min'],taught['envelope'][k]['max']) for k in KEYS[:3]}
    high=max(300,home['Z'],goal['Z'])
    routes={'direct':[goal], 'clearance':[dict(home,Z=high),dict(goal,Z=high),goal]}
    candidates={}
    for name,vertices in routes.items():
        try:candidates[name]=dict(ik_valid=True,**validate_candidate(home,q,vertices,taught['config'],env,taught['taught_joints']))
        except Exception as e:candidates[name]=dict(ik_valid=False,reason=str(e))
    feasible=[name for name,c in candidates.items() if c['ik_valid']]
    shortest=min(feasible,key=lambda name:candidates[name]['path_length_mm']) if feasible else None
    record=dict(status='offline_candidates_only',home=home,home_joints=q,goal=goal,
        source_sha256=hashlib.sha256(raw).hexdigest(),home_source_sha256=home_sha,
        candidates=candidates,shortest_ik_candidate=shortest,
        shortest_claim='Shortest XYZ length among these candidates; not globally shortest or collision-verified.',
        travel_gripper_mm=28,e2_degrees=taught['e2_degrees'],further_descent_z=None,
        grip_command=None,needs_route_clearance_review=True,execution_authorized=False,
        note='Open jaws at Home after startup; preserve E2. Do not run legacy calibration, which resets E2.')
    with path.open('x') as f:json.dump(record,f,indent=2,allow_nan=False)
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('capture','plan'))
    parser.add_argument('--position-confirmed',action='store_true')
    args=parser.parse_args()
    result=capture(args.position_confirmed) if args.action=='capture' else plan()
    print(json.dumps(result,indent=2))
