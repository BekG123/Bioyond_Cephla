"""Offline three-segment approximation of the successful level Hamilton transit.

Minimize worst normalized XYZ/yaw deviation over ordered retained vertices.
This is a geometric approximation, not a collision or dynamic smoothness proof.
"""
import hashlib
import json
import math
from pathlib import Path
from plan_hamilton_reteach_constant_height import SESSION
from plan_short_side_hamilton import validate

PARENT=SESSION/'constant_height_order_preserving_ik.json'
PLAN=SESSION/'smooth_three_transit_ik.json'
PARENT_SHA='fd1907a550f91c4d934cbb3734a9a8a609c442a2035a98e9b75718391c30b3c8'
KEYS=('X','Y','Z','Rz')


def error(points,a,b):
    start,end=points[a],points[b]
    delta=[end[k]-start[k] for k in KEYS]
    norm=sum(v*v for v in delta)
    errors=[]
    for point in points[a:b+1]:
        t=max(0,min(1,sum((point[k]-start[k])*v for k,v in zip(KEYS,delta))/norm)) if norm else 0
        projected={k:start[k]+t*v for k,v in zip(KEYS,delta)}
        errors.append((math.dist([point[k] for k in KEYS[:3]],[projected[k] for k in KEYS[:3]]),
                       abs(point['Rz']-projected['Rz'])))
    return dict(cost=max(max(x,y) for x,y in errors),xyz_mm=max(x for x,y in errors),yaw_deg=max(y for x,y in errors))


def build():
    raw=PARENT.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PARENT_SHA:raise ValueError('Successful parent route changed')
    parent=json.loads(raw);r=parent['routes']['forward']
    # Preserve the initial vertical clearance and both final vertical speed phases.
    level=r['points'][:-2]
    if {p['Z'] for p in level}!={98.6}:raise ValueError('Parent transit is no longer level')
    costs={(a,b):error(level,a,b) for a in range(len(level)-1) for b in range(a+1,len(level))}
    candidates=[]
    for a in range(1,len(level)-2):
        for b in range(a+1,len(level)-1):
            spans=[(0,a),(a,b),(b,len(level)-1)]
            candidates.append((max(costs[s]['cost'] for s in spans),a,b))
    _,a,b=min(candidates)
    transit=[level[a],level[b],level[-1]]
    points=[level[0]]+transit+r['points'][-2:]
    speeds=[137]*5+[5]
    f=validate(r['start'],points,r['start_joints'],parent['config'],parent['station_envelope'],r['validation']['endpoint_joints'])
    reverse=list(reversed([r['start']]+points))[1:]
    back=validate(points[-1],reverse,f['endpoint_joints'],parent['config'],parent['station_envelope'],r['start_joints'])
    if not f['workspace_valid'] or not back['workspace_valid']:raise ValueError('Candidate leaves workspace')
    errors=[costs[s] for s in [(0,a),(a,b),(b,len(level)-1)]]
    return dict(status='offline_candidate_requires_new_clearance_review',hardware_tested=False,
        parent_sha256=PARENT_SHA,selected_parent_transit_indices=[a,b,len(level)-1],
        transit_targets=transit,transit_waypoints=3,total_queue_targets=6,completion_barriers=1,
        comparison=dict(max_xyz_deviation_mm=max(e['xyz_mm'] for e in errors),
                        max_yaw_deviation_deg=max(e['yaw_deg'] for e in errors),
                        metric='Ordered parent vertices projected in XYZ/yaw with 1 mm and 1 degree equal weights; not a swept-volume bound'),
        config=parent['config'],global_envelope=parent['global_envelope'],station_envelope=parent['station_envelope'],
        routes=dict(forward=dict(start=r['start'],start_joints=r['start_joints'],points=points,segment_speeds=speeds,validation=f),
                    reverse=dict(start=points[-1],start_joints=f['endpoint_joints'],points=reverse,segment_speeds=list(reversed(speeds)),validation=back)),
        unchanged=['Initial vertical clearance','Level transit at Z98.60','Original Hamilton endpoint','Final descent speed5','No intermediate IDLE'],
        limitations=['Fewer linear segments do not guarantee continuous velocity or acceleration.',
                     'Existing Lua zone and completion behavior unchanged; no guessed corner blending.',
                     'The new wrist/plate sweep differs from the successful path and requires physical clearance review.'])


if __name__=='__main__':
    p=build()
    with PLAN.open('x',encoding='utf-8') as f:json.dump(p,f,indent=2,allow_nan=False)
    print(json.dumps(dict(path=str(PLAN),targets=p['transit_targets'],comparison=p['comparison'],
                         ik_samples=len(p['routes']['forward']['validation']['dense_samples'])),indent=2))
