"""Offline endpoint feasibility search. No robot connection or motion.

Uses the recorded 2026-09-14 calibrated plate pose, not live state.
The rectangle projection is necessary jaw clearance, not collision proof.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy import alignment_plan, TransferError

UI = Path(__file__).resolve().parents[1]
P = json.loads((UI / 'robot_params.json').read_text())
CAL = json.loads((UI.parent / 'grab_skill/calibration.json').read_text())
START = dict(X=293.115, Y=56.588, Z=270.453, Rz=-6.443)
JOINTS = dict(J1=231.854, J2=82.53354, J3=52.34679, J4=-141.3234)
CENTER = (310.88, 120.64)
DISK_YAW = 85.16
WIDTH, LENGTH = 85., 128.6
# Diagnostic bounds only; never applied to the robot.
ENV = dict(X=(0, 550), Y=(-350,350), Z=(0,420))

def endpoint(yaw):
    a = math.radians(yaw)
    cx, cy = CAL['claw_arm_tool_mm']
    return CENTER[0]-cx*math.cos(a)+cy*math.sin(a), CENTER[1]-cx*math.sin(a)-cy*math.cos(a)

def same_branch(x, y):
    x -= P['base_x_mm']; y -= P['base_y_mm']
    c = (x*x+y*y-80000)/80000
    if abs(c) >= 1:
        return None
    # Current J3 is positive: beta = J3+180, with negative sine.
    beta = -math.acos(c)
    q2 = math.degrees(math.atan2(y,x)-math.atan2(200*math.sin(beta),200+200*math.cos(beta)))
    q3 = math.degrees(beta)+180
    return q2,q3

def search(disk_yaw):
    feasible, fitting = [], []
    width_yaw = disk_yaw+CAL['wrist_rel_deg']
    for step in range(3600):
        yaw = -180+step/10
        angle = math.radians(yaw-width_yaw)
        span = WIDTH*abs(math.cos(angle))+LENGTH*abs(math.sin(angle))
        if span > P['claw_gap_max_mm']:
            continue
        x,y = endpoint(yaw)
        q = same_branch(x,y)
        r = math.hypot(x-P['base_x_mm'], y-P['base_y_mm'])
        row = dict(rz=round(yaw,1), span=span, radius=r, joints=q, tcp=[x,y])
        fitting.append(row)
        if not q or abs(q[0])>93 or r>383:
            continue
        try:
            plan = alignment_plan(START,dict(x=x,y=y,rz=yaw,z_calibrated=34),JOINTS,P,ENV,300)
            feasible.append({**row,'waypoints':len(plan)})
        except TransferError:
            pass
    return fitting,feasible

if __name__ == '__main__':
    fitting,valid = search(DISK_YAW)
    near = [v for v in fitting if v['tcp'][0]<CENTER[0]]
    far = [v for v in fitting if v['tcp'][0]>=CENTER[0]]
    _, rotated = search(DISK_YAW+90)
    print(json.dumps(dict(
        source='recorded pose; offline only; no mesh collision validation',
        yaw_samples=3600, jaw_fitting_samples=len(fitting), valid_current_paths=valid,
        near_branch_min_J2=min(v['joints'][0] for v in near if v['joints']),
        far_min_radius_mm=min(v['radius'] for v in far),
        hypothetical_plate_rotation_90deg_valid_count=len(rotated),
        hypothetical_example=min(rotated,key=lambda v:abs(v['rz']-83.54)) if rotated else None
    ),indent=2))
