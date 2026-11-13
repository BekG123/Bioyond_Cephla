"""Offline analysis of the November 11 demonstration; never connects to hardware."""
import hashlib
import json
from pathlib import Path

from plan_short_side_hamilton import validate

ROOT = Path(__file__).resolve().parent
SESSION = ROOT / 'reports/plate_session/hamilton_three_waypoint_teaching_20261111_154732'
PARENT = ROOT / 'reports/plate_session/cellvis24_validation/hamilton_rack_taught_pivot_plan_v2.json'
KEYS = ('X', 'Y', 'Z', 'Rz')


def build():
    raw = (SESSION / 'samples.jsonl').read_bytes()
    samples = [json.loads(line) for line in raw.splitlines()]
    measured = [s for s in samples if s.get('robot', {}).get('pose_mm')]
    by_index = {s['index']: s for s in measured}
    parent = json.loads(PARENT.read_bytes())
    baseline = parent['routes']['forward']
    pose = lambda s: {k: s['robot']['pose_mm'][k] for k in KEYS}
    start_sample = measured[0]
    start = pose(start_sample)
    joints = start_sample['robot']['joints']
    # Last measured turning-area sample before the sustained crossing. Preserve
    # its measured yaw rather than substituting a turn at HOME (which collided).
    pivot = pose(by_index[211])
    endpoint = dict(baseline['points'][-1])
    assert endpoint == dict(X=372.43, Y=-186.67, Z=53.72, Rz=-93.02)
    hover = dict(endpoint, Z=pivot['Z'])
    points = [pivot, hover, endpoint]
    forward = validate(start, points, joints, parent['config'], parent['station_envelope'],
                       baseline['validation']['endpoint_joints'])
    reverse_points = list(reversed([start] + points))[1:]
    reverse = validate(endpoint, reverse_points, forward['endpoint_joints'], parent['config'],
                       parent['station_envelope'], joints)
    assert forward['workspace_valid'] and reverse['workspace_valid']
    record = dict(
        status='offline_ik_checked_not_executable', motion_sent=False,
        execution_enabled=False, existing_routes_changed=False,
        samples_sha256=hashlib.sha256(raw).hexdigest(),
        parent_sha256=hashlib.sha256(PARENT.read_bytes()).hexdigest(),
        parent=str(PARENT), source=str(SESSION / 'samples.jsonl'),
        total_samples=len(samples), samples_with_pose=len(measured),
        first_pose_sample=start_sample['index'], last_pose_sample=measured[-1]['index'],
        disconnected_initial_samples=start_sample['index'],
        operator_feedback='Demonstration complete; three waypoints or fewer; preserve original Hamilton destination.',
        measured_teaching_end=pose(measured[-1]), endpoint_preserved=endpoint,
        selected_pivot_sample=211, config=parent['config'], station_envelope=parent['station_envelope'],
        routes=dict(
            forward=dict(start=start, start_joints=joints, points=points,
                         segment_speeds=[137, 137, 5], validation=forward),
            reverse=dict(start=endpoint, start_joints=forward['endpoint_joints'],
                         points=reverse_points, segment_speeds=[5, 137, 137], validation=reverse)),
        queue_intent=dict(queues_per_direction=1, segment_kind='MoveL', final_barriers=1,
                          note='Planning only; no queue uploaded or executor enabled.'),
        limitations=[
            'Starts at first captured pose, NOT the HOME pickup pose. Initial teaching movement was not captured.',
            'HOME-to-captured-start connection is unresolved and not included in the three target count.',
            'Simplified first leg combines translation and yaw; demonstration first moved to the turning area then rotated. Swept clearance is not established.',
            'Crossing uses the demonstrated Z110.64; this differs from the previously accepted rack crossing at Z77. Physical clearance remains unverified.',
            'Endpoint is the original taught Hamilton endpoint, not the final manual demonstration pose.',
            'Final vertical seating is entirely speed 5 to keep three targets; a separate fast descent boundary would add another target.',
            'Controller faults were present while teaching. Pose observations are not successful powered trial evidence.',
            'Dense IK and workspace checks do not establish collision clearance; no automatic replay or fault recovery.'])
    return record


if __name__ == '__main__':
    record = build()
    output = SESSION / 'three_waypoint_ik_candidate.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(path=str(output), status=record['status'],
        start=record['routes']['forward']['start'], points=record['routes']['forward']['points'],
        length_mm=record['routes']['forward']['validation']['length_mm'],
        joint_ranges=record['routes']['forward']['validation']['joint_ranges'],
        forward_dense_samples=len(record['routes']['forward']['validation']['dense_samples']),
        reverse_dense_samples=len(record['routes']['reverse']['validation']['dense_samples'])), indent=2))
