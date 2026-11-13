"""Offline revision06: retain the corrected turn, cross into Hamilton at Z77."""
import hashlib
import json
import time

from hamilton_rack_clearance import FOLDER, TURN05_PLAN, turn05_reference
from plan_short_side_hamilton import validate
from trajectory_queue import checksum

OUTPUT = FOLDER/'corrected_turn06_z77.json'


def build():
    prior, parent = turn05_reference()
    forward = prior['forward']
    old = forward['points']
    # Finish the unchanged turn outside Hamilton, then lower before crossing.
    points = old[:2] + [dict(old[1], Z=77.0), dict(old[2], Z=77.0)] + old[3:]
    speeds = [40] * (len(points)-1) + [5]
    start, joints = forward['start'], forward['start_joints']
    cfg, env = parent['config'], parent['station_envelope']
    checked = validate(start, points, joints, cfg, env, forward['validation']['endpoint_joints'])
    back = list(reversed([start] + points))[1:]
    reverse = validate(points[-1], back, checked['endpoint_joints'], cfg, env, joints)
    if not checked['workspace_valid'] or not reverse['workspace_valid']:
        raise ValueError('Candidate outside station envelope')
    return dict(revision='06_z77', created_at=time.time(),
        status='offline_checked_not_physically_tested',
        operator_request='Cross into Hamilton at Z77; keep placement at Z53.72.',
        parent_file=str(TURN05_PLAN), parent_sha256=hashlib.sha256(TURN05_PLAN.read_bytes()).hexdigest(),
        config=cfg, global_envelope=parent['global_envelope'], station_envelope=env,
        forward=dict(start=start, start_joints=joints, points=points, segment_speeds=speeds,
                     checksum=checksum(points, speeds), validation=checked),
        reverse=dict(start=points[-1], start_joints=checked['endpoint_joints'], points=back,
                     segment_speeds=list(reversed(speeds)), checksum=checksum(back, list(reversed(speeds))), validation=reverse),
        final_destination_unchanged=True, turn_unchanged=True, crossing_z_mm=77,
        global_limits_changed=False, motion_sent=False, collision_clearance_verified=False,
        payload='empty only')


if __name__ == '__main__':
    result = build()
    with OUTPUT.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(file=str(OUTPUT), sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                         points=result['forward']['points'], forward_ik=True, reverse_ik=True)))
