"""Offline waypoint-count comparison. No controller access or route installation."""
import argparse
import hashlib
import json
from pathlib import Path
from plan_hamilton_smooth_transit import PARENT,PLAN,PARENT_SHA,error
from plan_short_side_hamilton import validate


def compare():
    raw=PARENT.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PARENT_SHA:
        raise ValueError('Recorded parent route changed.')
    parent=json.loads(raw);accepted=json.loads(PLAN.read_bytes())
    route=parent['routes']['forward'];level=route['points'][:-2]
    costs={(a,b):error(level,a,b) for a in range(len(level)-1) for b in range(a+1,len(level))}
    pivot=min(range(1,len(level)-1),key=lambda i:max(costs[0,i]['cost'],costs[i,len(level)-1]['cost']))
    baseline=accepted['routes']['forward']['points']
    variants={
        'accepted_six':baseline,
        'five_keep_first_turn':[baseline[i] for i in (0,1,3,4,5)],
        'five_keep_second_turn':[baseline[i] for i in (0,2,3,4,5)],
        'five_best_recorded_turn':[level[0],level[pivot],level[-1],*route['points'][-2:]],
        'four_direct_level':[level[0],level[-1],*route['points'][-2:]],
    }
    results={}
    for name,points in variants.items():
        indices=[level.index(p) for p in points[:-2]]
        spans=list(zip(indices,indices[1:]))
        row=dict(points=points,total_targets=len(points),transit_targets=len(points)-3,
                 segment_speeds=[137]*(len(points)-1)+[5],
                 max_parent_xyz_deviation_mm=max(costs[s]['xyz_mm'] for s in spans),
                 max_parent_yaw_deviation_deg=max(costs[s]['yaw_deg'] for s in spans),
                 hardware_tested=name=='accepted_six',execution_enabled=False)
        try:
            forward=validate(route['start'],points,route['start_joints'],parent['config'],
                             parent['station_envelope'],route['validation']['endpoint_joints'])
            back=validate(points[-1],list(reversed([route['start']]+points))[1:],
                          forward['endpoint_joints'],parent['config'],parent['station_envelope'],route['start_joints'])
            row.update(forward=forward,reverse=back)
        except ValueError as exc:row['error']=str(exc)
        results[name]=row
    return dict(motion_sent=False,active_path_changed=False,
        parent_sha256=PARENT_SHA,accepted_route_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        candidates=results,
        preserved=['Initial vertical clearance','Level transit Z98.60','Hamilton XY/yaw endpoint',
                   'Speed transition at Z77','Final seating at Z53.72, speed5'],
        limitations=['Deviation uses ordered parent vertices in XYZ/yaw with 1 mm/1 degree equal weights.',
                     'IK and workspace feasibility do not establish rack/plate/claw clearance.',
                     'No measured timing or smoothness prediction; current blended Lua accepts only six targets.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Preserve existing comparison; use a new output path.')
    report=compare()
    with args.output.open('x') as stream:json.dump(report,stream,indent=2,allow_nan=False)
    for name,row in report['candidates'].items():
        forward=row.get('forward',{})
        print(json.dumps(dict(name=name,targets=row['total_targets'],
            length_mm=forward.get('length_mm'),max_xyz_deviation_mm=row['max_parent_xyz_deviation_mm'],
            max_yaw_deviation_deg=row['max_parent_yaw_deviation_deg'],
            forward_ik=forward.get('ik_and_joint_limits_valid'),workspace=forward.get('workspace_valid'),
            reverse_ik=row.get('reverse',{}).get('ik_and_joint_limits_valid'),error=row.get('error'))),flush=True)
