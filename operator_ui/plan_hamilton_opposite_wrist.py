"""Offline IK comparison using dense teaching and continuous wrist winding.

Never dispatches, clears faults, changes limits, or replaces a live route.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from autonomy import check_path
from plan_short_side_hamilton import validate
from plan_hamilton_smooth_transit import PLAN,KEYS


def deviation(points,a,b):
    p=np.array([[p[k] for k in KEYS] for p in points[a:b+1]])
    delta=p[-1]-p[0];norm=delta@delta
    t=np.clip((p-p[0])@delta/norm,0,1) if norm else np.zeros(len(p))
    e=p-(p[0]+t[:,None]*delta)
    xyz=float(np.linalg.norm(e[:,:3],axis=1).max());yaw=float(abs(e[:,3]).max())
    return dict(cost=max(xyz,yaw),xyz_mm=xyz,yaw_deg=yaw)


def build(session):
    raw=(session/'samples.jsonl').read_bytes()
    rows=[json.loads(line) for line in raw.splitlines()]
    if any(not r.get('valid') for r in rows):raise ValueError('Recording contains invalid feedback; inspect before fitting.')
    angles=np.rad2deg(np.unwrap(np.deg2rad([r['robot']['pose_mm']['Rz'] for r in rows])))
    parent=json.loads(PLAN.read_bytes());old=parent['routes']['forward']
    endpoint=dict(old['points'][-1]);endpoint['Rz']+=360
    expected=dict(old['validation']['endpoint_joints']);expected['J4']+=360
    # Separate outward demonstrations from their return/reset legs. Select
    # the outbound pass closest to the established Hamilton XY/yaw endpoint.
    passes=[];active=False;start=0
    for i,yaw in enumerate(angles):
        if not active and yaw<=95:start=i
        if not active and yaw>120:active=True
        if active and yaw<120:
            finish=min(range(start,i),key=lambda j:math.hypot(rows[j]['robot']['pose_mm']['X']-endpoint['X'],rows[j]['robot']['pose_mm']['Y']-endpoint['Y'])+abs(angles[j]-endpoint['Rz']))
            pose=rows[finish]['robot']['pose_mm']
            score=math.hypot(pose['X']-endpoint['X'],pose['Y']-endpoint['Y'])+abs(angles[finish]-endpoint['Rz'])
            passes.append(dict(start=start,end=finish,return_before=i,score=score,
                               time_s=[rows[start]['elapsed_s'],rows[finish]['elapsed_s']]))
            active=False
    selected=min(passes,key=lambda p:p['score'])
    taught=[dict((k,r['robot']['pose_mm'][k]) for k in KEYS) for r in rows[selected['start']:selected['end']+1]]
    for p,a in zip(taught,angles[selected['start']:selected['end']+1]):p['Rz']=float(a)
    height=round(float(np.median([p['Z'] for p in taught])),2)
    if max(abs(p['Z']-height) for p in taught)>.05:raise ValueError('Nonlevel teaching needs separate handling.')
    above=dict(old['start'],Z=height);entry=dict(endpoint,Z=height)
    level=[above]+taught+[entry]
    costs={(a,b):deviation(level,a,b) for a in range(len(level)-1) for b in range(a+1,len(level))}
    last=len(level)-1
    one=min(range(1,last),key=lambda i:max(costs[0,i]['cost'],costs[i,last]['cost']))
    two=min(((a,b) for a in range(1,last-1) for b in range(a+1,last)),
            key=lambda ab:max(costs[0,ab[0]]['cost'],costs[ab]['cost'],costs[ab[1],last]['cost']))
    candidates={}
    for name,indices in [('direct_four',[0,last]),('one_turn_five',[0,one,last]),('two_turn_six',[0,*two,last])]:
        points=[level[i] for i in indices]+[dict(endpoint,Z=77),endpoint]
        points=[{k:math.floor(p[k]*100+.5)/100 for k in KEYS} for p in points]
        spans=list(zip(indices,indices[1:]))
        row=dict(points=points,segment_speeds=[137]*(len(points)-1)+[5],
                 selected_recording_indices=[None if i in (0,last) else selected['start']+i-1 for i in indices],
                 max_recorded_xyz_deviation_mm=max(costs[s]['xyz_mm'] for s in spans),
                 max_recorded_yaw_deviation_deg=max(costs[s]['yaw_deg'] for s in spans))
        try:
            # Check actual command legs as well as dense samples, including
            # the existing near-180-degree ambiguity rejection.
            q=dict(old['start_joints']);previous=old['start']
            for point in points:q=check_path(previous,point,q,parent['config'],parent['station_envelope']);previous=point
            forward=validate(old['start'],points,old['start_joints'],parent['config'],parent['station_envelope'],expected)
            reverse_points=list(reversed([old['start']]+points))[1:]
            reverse=validate(endpoint,reverse_points,forward['endpoint_joints'],parent['config'],parent['station_envelope'],old['start_joints'])
            row.update(forward=forward,reverse=reverse,valid=forward['workspace_valid'] and reverse['workspace_valid'])
        except Exception as error:row.update(valid=False,error=str(error))
        candidates[name]=row
    return dict(status='offline_candidate_not_installed',motion_sent=False,execution_enabled=False,
        source=str(session),recording_sha256=hashlib.sha256(raw).hexdigest(),samples=len(rows),
        effective_rate_hz=(len(rows)-1)/(rows[-1]['elapsed_s']-rows[0]['elapsed_s']),passes=passes,selected_pass=selected,
        source_z_range=[min(p['Z'] for p in taught),max(p['Z'] for p in taught)],
        current_recorded_pose=rows[-1]['robot']['pose_mm'],home_start=old['start'],
        original_hamilton_endpoint=old['points'][-1],continuous_yaw_endpoint=endpoint,
        original_endpoint_joints=old['validation']['endpoint_joints'],opposite_endpoint_joints=expected,
        candidates=candidates,config=parent['config'],station_envelope=parent['station_envelope'],
        selection_note='Minimum worst XYZ/yaw teaching deviation for each target count, not a globally shortest collision-free solution.',
        limitations=['Initial HOME lift and exact Hamilton descent are connectors, not this demonstration.',
                     'Empty disabled-arm demonstration does not establish loaded clearance.',
                     'Unwrapped positive yaw preserves the taught physical J4 winding; old negative-winding endpoint bindings cannot be reused.',
                     'Current six-point blend protocol is pinned to the previous route; these candidates are not executable through it.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--session',type=Path,required=True)
    args=parser.parse_args();output=args.session/'opposite_wrist_ik.json'
    if output.exists():raise ValueError('Preserve existing evidence; use a new version.')
    report=build(args.session)
    with output.open('x') as stream:json.dump(report,stream,indent=2,allow_nan=False)
    for name,c in report['candidates'].items():
        print(json.dumps(dict(name=name,valid=c['valid'],points=c['points'],
            length_mm=c.get('forward',{}).get('length_mm'),xyz_deviation=c['max_recorded_xyz_deviation_mm'],
            yaw_deviation=c['max_recorded_yaw_deviation_deg'],joints=c.get('forward',{}).get('endpoint_joints'),error=c.get('error'))))
    print(str(output))
