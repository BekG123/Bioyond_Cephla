"""Read-only return-path feasibility check; never issues hardware commands.

Reach and envelope checks do not verify clearance from the rack or other objects.
"""
import json
import urllib.request
from hotel_rehearsal import ROOT, check_path, split_leg


def main():
    with urllib.request.urlopen('http://127.0.0.1:5002/state', timeout=5) as response:
        state = json.load(response)
    pose = state['robot']['pose_mm']
    joints = state['robot']['joints']
    params = json.loads((ROOT/'operator_ui/robot_params.json').read_text())
    goal = json.loads((ROOT/'mujoco_sim/current_pose_snapshot_20261009.json').read_text())['robot']['pose_mm']
    envelope = {k: (state['envelope'][k]['min'], state['envelope'][k]['max']) for k in ('X', 'Y', 'Z')}
    high = {**pose, 'X': goal['X'], 'Y': goal['Y']}
    turned = {**high, 'Rz': goal['Rz']}
    result = []
    for phase, target in [('return XY at current height', high),
                          ('restore yaw at height', turned), ('restore original Z', goal)]:
        previous_j1 = joints['J1']
        joints = check_path(pose, target, joints, params, envelope)
        joints['J1'] = previous_j1 + target['Z'] - pose['Z']
        result.append(dict(phase=phase, target=target, predicted_joints=joints,
                           segments=len(split_leg(pose, target))))
        pose = target
    print(json.dumps(dict(preview_only=True, collision_clearance_verified=False,
                          current=state['robot'], legs=result), indent=2))


if __name__ == '__main__':
    main()
