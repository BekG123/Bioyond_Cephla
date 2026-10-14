"""Recorded Home -> centered ID 1 view. Dry-run by default (no network).

Execute only while supervised at E-stop with the recorded route clear:
  py operator_ui/home_to_aruco.py --execute --operator-confirmed --cell-clear
Robot must ALREADY be at saved Home, auto/enabled/running, gripper empty.
No enable, program restart, envelope edits, return-home, descent or grip.
"""
import argparse
import json
import math
from pathlib import Path
from autonomy import check_path, ensure_arrival, TransferError
from sequences import get_robot_params

PATH = Path(__file__).with_name('home_to_aruco_path.json')

def plan(data, start, joints, envelope):
    points = [dict(X=x,Y=y,Z=data['Z'],Rz=data['Rz']) for x,y in data['xy_waypoints']]
    pose, q = start, joints
    for point in points:
        q = check_path(pose,point,q,get_robot_params(),envelope)
        pose = point
    return points

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--operator-confirmed',action='store_true')
    parser.add_argument('--cell-clear',action='store_true')
    args = parser.parse_args()
    data=json.loads(PATH.read_text())
    points=plan(data,data['home'],data['home_joints'],data['envelope'])
    if not args.execute:
        print(json.dumps(dict(dry_run=True,waypoints=len(points),end=points[-1],
                              note='No network/motion. Joint/envelope checks only; no collision certification.'),indent=2))
        return
    if not (args.operator_confirmed and args.cell_clear):
        raise TransferError('fresh operator/E-stop and clear-route confirmation required')
    from find_from_home_step import api,ready
    from center_marker_step import measure
    state=ready()
    ensure_arrival(state['robot']['pose_mm'],data['home'])
    for key,value in data['home_joints'].items():
        if abs(state['robot']['joints'][key]-value)>0.5:
            raise TransferError('not at recorded Home joint configuration')
    report=api('/gripper',{'action':'torque'})
    if not report.get('telemetry_live') or not math.isfinite(report['e1_torque']) or report['e1_torque'] < -100:
        raise TransferError('empty gripper/live telemetry not confirmed')
    env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    # Use intersection: a broader live box must not relax the recorded route.
    env={k:(max(v[0],data['envelope'][k][0]),min(v[1],data['envelope'][k][1])) for k,v in env.items()}
    points=plan(data,state['robot']['pose_mm'],state['robot']['joints'],env)
    expected=state['robot']['pose_mm']
    for point in points:
        state=ready()
        ensure_arrival(state['robot']['pose_mm'],expected)
        check_path(state['robot']['pose_mm'],point,state['robot']['joints'],get_robot_params(),env)
        result=api('/move',dict(x=point['X'],y=point['Y'],z=point['Z'],rz=point['Rz'],speed=5,interpolation='linear'))
        ensure_arrival(result['pose_after'],point)
        ensure_arrival(ready()['robot']['pose_mm'],point)
        expected=point
        print(json.dumps({'arrived':point}),flush=True)
    # Fresh vision is mandatory before describing the endpoint as centered.
    _,delta=measure()
    if math.hypot(*delta)>1:
        raise TransferError('recorded endpoint reached but ID 1 not centered; stopped, no blind correction')
    print('ID 1 centered. Stopped BEFORE grasp alignment, descent or grip.')

if __name__ == '__main__':
    main()
