"""Offline HOME-to-Hamilton three-target candidate from the recorded teaching.

Does not connect, upload, select a live route, or change controller limits.
"""
import argparse
import hashlib
import json
import math

from cellvis24_rack_route import reference, PLAN, PLAN_SHA
from plan_hamilton_teaching_20261111 import SESSION, KEYS
from plan_short_side_hamilton import validate
from trajectory_queue import checksum

OUTPUT = SESSION / 'home_hamilton_three_waypoint_ik_queue_v2.json'


def build():
    parent = reference()
    source = SESSION / 'samples.jsonl'
    raw = source.read_bytes()
    samples = [json.loads(line) for line in raw.splitlines()]
    # Taught turning-area position immediately before the sustained clockwise
    # wrist turn. Using this intermediate yaw splits the total -180.9 degree
    # change into two segments smaller than 180, preserving its winding.
    sample = next(s for s in samples if s['index'] == 191)
    pivot = {k: math.floor(sample['robot']['pose_mm'][k] * 100 + .5) / 100 for k in KEYS}
    f = parent['routes']['forward']
    start = dict(f['start'])
    endpoint = dict(f['points'][-1])
    assert endpoint == dict(X=372.43, Y=-186.67, Z=53.72, Rz=-93.02)
    points = [pivot, dict(endpoint, Z=77.0), endpoint]
    speeds = [137, 137, 5]
    previous = start
    for point in points:
        if abs(point['Rz'] - previous['Rz']) >= 180:
            raise ValueError('Ambiguous wrist winding')
        previous = point
    forward = validate(start, points, f['start_joints'], parent['config'],
                       parent['station_envelope'], f['validation']['endpoint_joints'])
    back = list(reversed([start] + points))[1:]
    reverse = validate(endpoint, back, forward['endpoint_joints'], parent['config'],
                       parent['station_envelope'], f['start_joints'])
    if not forward['workspace_valid'] or not reverse['workspace_valid']:
        raise ValueError('Configured station envelope exceeded')
    return dict(
        status='offline_ik_valid_pending_swept_clearance', execution_enabled=False,
        motion_sent=False, existing_route_replaced=False,
        parent=str(PLAN), parent_sha256=PLAN_SHA,
        recording=str(source), recording_sha256=hashlib.sha256(raw).hexdigest(),
        taught_pivot_sample=191, endpoint_preserved=True,
        start_contract='Known short-side HOME pickup after the existing 5 mm proof lift; not IDLE and not the current live pose.',
        config=parent['config'], station_envelope=parent['station_envelope'],
        routes=dict(
            forward=dict(start=start, start_joints=f['start_joints'], points=points,
                         segment_speeds=speeds, kinds=['L'] * 3, validation=forward),
            reverse=dict(start=endpoint, start_joints=forward['endpoint_joints'], points=back,
                         segment_speeds=list(reversed(speeds)), kinds=['L'] * 3, validation=reverse)),
        queue_intent=dict(queues_per_direction=1, completion_barriers=1,
                          points_after_start=3, forward_geometry_checksum=checksum(points),
                          reverse_geometry_checksum=checksum(back), upload_performed=False,
                          note='One queued coordinated XYZ/yaw path; no separate stationary wrist turns. Exact controller timing/blending requires runtime validation.'),
        comparison=dict(parent_points=len(f['points']), new_points=3,
                        parent_length_mm=f['validation']['length_mm'],
                        candidate_length_mm=forward['length_mm']),
        constraints_unchanged=['Hamilton endpoint', 'Existing station-specific envelope',
                               'J4 +/-220 degrees', 'Short-side grip and proof-lift preparation'],
        limitations=[
            'HOME-to-turning-area connector is calculated from the known HOME pose; its manual demonstration was not captured.',
            'First segment translates, rises and rotates 46.867 degrees. It must clear HOME and the rack; the previous stationary turn above HOME physically collided.',
            'Second segment combines the demonstrated wrist turn with translation and descent to Z77. This is not an exact replay of the manual turn-then-cross sequence.',
            'No geometric collision model or verified swept-volume clearance is available for the changed rack route. IK validity is not collision clearance.',
            'Keeping exactly three targets makes the entire Z77-to-Z53.72 seating segment speed 5. An additional fast/slow transition would require a fourth target.',
            'Reverse ends at the HOME proof-lift pose. Existing slow reseating and release remain separate handling steps.',
            'This is not a recovery route from the current stopped/caught arm pose. No fault reset or live motion is authorized by this artifact.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save', action='store_true')
    args = parser.parse_args()
    result = build()
    if args.save:
        with OUTPUT.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
    forward = result['routes']['forward']
    reverse = result['routes']['reverse']
    print(json.dumps(dict(saved=str(OUTPUT) if args.save else None,
        status=result['status'], start=forward['start'], points=forward['points'],
        speeds=forward['segment_speeds'], comparison=result['comparison'],
        joint_ranges=forward['validation']['joint_ranges'],
        forward_samples=len(forward['validation']['dense_samples']),
        reverse_samples=len(reverse['validation']['dense_samples'])), indent=2))


if __name__ == '__main__':
    main()
