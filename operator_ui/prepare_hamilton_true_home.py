"""Export the direct Home candidate and offline comparison. Never connects to hardware."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import argparse

from hamilton_true_home import configured, check_route, requirement, ROOT, station_reference
from latest_hamilton import LatestHamilton
from researcher_home import compact_home_connection
from scope_compact137 import accepted


def length(start, points):
    path=[start]+points
    return sum(math.dist([a[k] for k in ('X','Y','Z')],[b[k] for k in ('X','Y','Z')])
               for a,b in zip(path,path[1:]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='candidate.json',
                        help='New report filename; existing reports are never replaced.')
    args=parser.parse_args()
    if Path(args.output).name!=args.output:
        parser.error('output must be a filename')
    cfg=json.loads((ROOT/'robot_params.json').read_text(encoding='utf-8-sig'))
    route=configured();env=route['envelope']
    legacy=LatestHamilton(ROOT/'demonstrations/return_home_20261016_130748',
                          None,None,lambda:cfg,None,None)
    original,source_id,old=legacy.reviewed()
    _,_,_,trials=accepted()
    starts=dict(reverse=station_reference(original)[1],
                forward=trials['reverse']['final_robot']['joints'])
    validation={}
    for direction in ('forward','reverse'):
        path=route[direction]
        q,checked=check_route(path[0],path[1:],starts[direction],cfg,env,route)
        validation[direction]=dict(ik_passed=True,checked=checked,final_joints=q,
                                   length_mm=length(path[0],path[1:]),commands=3)
    old_reverse=list(reversed([old['start']]+old['points']))
    connector=compact_home_connection(old_reverse[-1],route['reverse'][-1],
        original['trajectory'][-1]['joints'],cfg,env)
    baseline_points=old_reverse[1:]+connector
    record=dict(schema='cephla.hamilton-true-home-review.v1',
        at=datetime.now(timezone.utc).isoformat(),status='offline_validated_pending_clearance',
        operator_feedback='Direct true Home route; Hamilton height requested at J1=0.00, rounded upward to queue resolution.',
        candidate=route,source_sha256=source_id,
        home_file_sha256=hashlib.sha256((ROOT/'points.json').read_bytes()).hexdigest(),
        cfg=cfg,validation=validation,
        baseline=dict(commands=len(baseline_points),
                      length_mm=length(old_reverse[0],baseline_points),points=baseline_points),
        clearance_requirement=requirement(route),speed=137,zone=-1,
        physical_clearance_verified=False,hardware_execution=False,
        collision_geometry='No surveyed obstacle model for this new connector; IK is not collision verification.',
        scope='Original Hamilton XY/wrist preserved; endpoint height revised separately. New connector remains inside normal workspace. '
              'No Home-area endpoint or hover. Original recordings retained.')
    folder=ROOT/'reports/trajectory_smoothing/direct_true_home'
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/args.output
    with path.open('x',encoding='utf-8') as stream:
        json.dump(record,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(report=str(path),reverse=route['reverse'],
        baseline_commands=len(baseline_points),new_commands=3,
        baseline_length_mm=record['baseline']['length_mm'],
        new_length_mm=validation['reverse']['length_mm'],
        clearance=requirement(route)),indent=2))


if __name__=='__main__':
    main()
