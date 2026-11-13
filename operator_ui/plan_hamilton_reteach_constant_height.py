"""Offline faithful approximation of the second Hamilton demonstration.

Never connects to the arm. Never replaces a live route. Preserves ordered
XYZ/yaw samples; appends explicitly unobserved endpoint connectors separately.
"""
import hashlib
import json
import math
from pathlib import Path
from cellvis24_rack_route import reference, PLAN_SHA
from plan_short_side_hamilton import validate

SESSION=Path(__file__).resolve().parent/'reports/plate_session/hamilton_reteach_after_three_point_contact_v2'
KEYS=('X','Y','Z','Rz')
XYZ_TOLERANCE=1.0
YAW_TOLERANCE=1.0


def deviation(point,start,end):
    scale=[XYZ_TOLERANCE]*3+[YAW_TOLERANCE]
    delta=[(end[k]-start[k])/s for k,s in zip(KEYS,scale)]
    offset=[(point[k]-start[k])/s for k,s in zip(KEYS,scale)]
    denom=sum(v*v for v in delta)
    t=max(0,min(1,sum(a*b for a,b in zip(offset,delta))/denom)) if denom else 0
    projected={k:start[k]+t*(end[k]-start[k]) for k in KEYS}
    xyz=math.dist([point[k] for k in KEYS[:3]],[projected[k] for k in KEYS[:3]])
    yaw=abs(point['Rz']-projected['Rz'])
    return max(xyz/XYZ_TOLERANCE,yaw/YAW_TOLERANCE),xyz,yaw


def simplify(points):
    keep={0,len(points)-1};pending=[(0,len(points)-1)]
    while pending:
        a,b=pending.pop()
        if b-a<=1:continue
        error,index=max((deviation(points[i],points[a],points[b])[0],i) for i in range(a+1,b))
        if error>1:
            keep.add(index);pending.extend([(a,index),(index,b)])
    return sorted(keep)


def build():
    raw=(SESSION/'samples.jsonl').read_bytes()
    samples=[json.loads(line) for line in raw.splitlines()]
    captured=[s for s in samples if s.get('robot',{}).get('pose_mm')]
    poses=[{k:s['robot']['pose_mm'][k] for k in KEYS} for s in captured]
    indices=simplify(poses)
    # Rounding only to the controller's 0.01-unit queue resolution. Do not
    # silently alter a measured height or straighten a turning arc.
    quantize=lambda p:{k:math.floor(p[k]*100+.5)/100 for k in KEYS}
    taught=[quantize(poses[i]) for i in indices]
    errors=[deviation(p,taught[j],taught[j+1]) for j,(a,b) in enumerate(zip(indices,indices[1:])) for p in poses[a:b+1]]
    parent=reference();baseline=parent['routes']['forward']
    start=baseline['start'];endpoint=baseline['points'][-1]
    if endpoint!=dict(X=372.43,Y=-186.67,Z=53.72,Rz=-93.02):raise ValueError('Hamilton endpoint changed')
    # Reach the demonstrated height first without sweeping the wrist while
    # rising out of HOME. Then connect to the captured start at that height.
    above_home=dict(start,Z=taught[0]['Z'])
    terminal=[dict(endpoint,Z=taught[-1]['Z']),dict(endpoint,Z=77),dict(endpoint)]
    points=[above_home]+taught+terminal
    speeds=[137]*(len(points)-1)+[5]
    forward=validate(start,points,baseline['start_joints'],parent['config'],parent['station_envelope'],baseline['validation']['endpoint_joints'])
    back=list(reversed([start]+points))[1:]
    reverse=validate(endpoint,back,forward['endpoint_joints'],parent['config'],parent['station_envelope'],baseline['start_joints'])
    if not forward['workspace_valid'] or not reverse['workspace_valid']:raise ValueError('Workspace violation')
    if max(e[1] for e in errors)>XYZ_TOLERANCE+.02 or max(e[2] for e in errors)>YAW_TOLERANCE+.02:
        raise ValueError('Quantized approximation exceeds declared bounds')
    return dict(status='offline_order_preserving_candidate_pending_review',motion_sent=False,execution_enabled=False,
        parent_sha256=PLAN_SHA,recording_sha256=hashlib.sha256(raw).hexdigest(),
        total_samples=len(samples),pose_samples=len(captured),initial_missing_s=captured[0]['elapsed_s'],
        raw_z_range=[min(p['Z'] for p in poses),max(p['Z'] for p in poses)],
        selected_recording_indices=[captured[i]['index'] for i in indices],
        taught_points=taught,taught_span_targets=len(taught)-1,
        approximation=dict(xyz_tolerance_mm=XYZ_TOLERANCE,yaw_tolerance_deg=YAW_TOLERANCE,
                           max_xyz_deviation_mm=max(e[1] for e in errors),max_yaw_deviation_deg=max(e[2] for e in errors),
                           note='Against recorded TCP poses/yaw only, not a collision-clearance or jerk bound.'),
        untaught_connectors=dict(home_to_recorded_start=[above_home,taught[0]],recorded_end_to_original_site4=terminal),
        config=parent['config'],global_envelope=parent['global_envelope'],station_envelope=parent['station_envelope'],
        routes=dict(forward=dict(start=start,start_joints=baseline['start_joints'],points=points,segment_speeds=speeds,validation=forward),
                    reverse=dict(start=endpoint,start_joints=forward['endpoint_joints'],points=back,segment_speeds=list(reversed(speeds)),validation=reverse)),
        queue_intent=dict(queues_per_direction=1,points_per_direction=len(points),completion_barriers=1,
                          note='No queue uploaded, no executor binding changed; speed137 transit and5 final seating are intent, not a tested runtime.'),
        preserved=['Measured order of inward retreat, turning arc and Hamilton approach','Measured constant travel height','Original Hamilton endpoint','No lowering during taught turning/crossing span'],
        limitations=['Demonstration was hand-guided with disabled servos; not a successful powered trial.',
                     'Initial21 seconds lacked telemetry; first captured pose then remained stationary before active teaching.',
                     'Known-HOME connector and final extension/descent were not demonstrated and require separate clearance review.',
                     'Retained multiple targets instead of forcing a three-target shortcut. One queue can contain all retained targets.',
                     'New contact state requires inspection before recovery; this is not a recovery path.'])


if __name__=='__main__':
    p=build();output=SESSION/'constant_height_order_preserving_ik.json'
    with output.open('x',encoding='utf-8') as f:json.dump(p,f,indent=2,allow_nan=False)
    print(json.dumps(dict(path=str(output),samples=p['pose_samples'],z_range=p['raw_z_range'],
        retained_taught_points=len(p['taught_points']),total_queue_targets=p['queue_intent']['points_per_direction'],
        approximation=p['approximation'],taught_points=p['taught_points'],
        forward_ik_samples=len(p['routes']['forward']['validation']['dense_samples']),
        reverse_ik_samples=len(p['routes']['reverse']['validation']['dense_samples'])),indent=2))
