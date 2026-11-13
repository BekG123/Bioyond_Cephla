"""Prepare the taught loaded slot-1 endpoint and horizontal Path A entry offline."""
import hashlib
import json
import math
from pathlib import Path
from home_squid_transfer import checked
from plan_short_side_hamilton import validate

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / 'operator_ui/reports/plate_session/hotel_slot1_loaded_teaching_20261111_222406'
PARENT = ROOT / 'operator_ui/reports/plate_session/hotel_slot_teaching_20261111_212833/slot_1_route_candidates_v1.json'
KEYS = ('X', 'Y', 'Z', 'Rz')


def build():
    capture_path = SESSION / 'slot_1_loaded_endpoint_capture.json'
    capture = json.loads(capture_path.read_bytes())
    parent = json.loads(PARENT.read_bytes())
    status = json.loads((SESSION / 'status.json').read_bytes())
    if status['recording']:
        raise ValueError('Finish recording before binding its evidence.')
    robot = capture['state']['robot']
    if not robot['connected'] or not robot['ok'] or robot['errors'] or capture['native']['moving']:
        raise ValueError('Endpoint requires valid stationary feedback.')
    end = {k: robot['pose_mm'][k] for k in KEYS}
    old = parent['candidates']['compact_three']['points']
    # Preserve Path A's XY insertion vector; translate its outside-entry point
    # with the newly taught endpoint. No yaw or height change inside the slot.
    entry = dict(end)
    for k in ('X', 'Y'):
        entry[k] = round(end[k] - (old[-1][k] - old[-2][k]), 3)
    turn = dict(old[0], Rz=end['Rz'])
    points = [turn, entry, end]
    start = parent['start']
    joints = parent['start_joints']
    forward = validate(start, points, joints, parent['config'], parent['envelope'], robot['joints'])
    reverse_points = [entry, turn, start]
    reverse = validate(end, reverse_points, robot['joints'], parent['config'], parent['envelope'], joints)
    quantized = [{k: math.floor(p[k] * 100 + .5) / 100 for k in KEYS} for p in points]
    transmitted = validate(start, quantized, joints, parent['config'], parent['envelope'], robot['joints'])
    if not all(v['workspace_valid'] for v in (forward, reverse, transmitted)):
        raise ValueError('Loaded candidate exceeds existing workspace.')
    assert entry['Z'] == end['Z'] and entry['Rz'] == end['Rz']
    raw = (SESSION / 'samples.jsonl').read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    valid = [r for r in rows if r.get('valid')]
    # Separate the previously accepted loaded proof lift from Path A's start.
    proof = {k: valid[0]['robot']['pose_mm'][k] for k in KEYS}
    proof_q = valid[0]['robot']['joints']
    connector_q = checked(proof, [start], proof_q, parent['config'], parent['envelope'])
    connector = validate(proof, [start], proof_q, parent['config'], parent['envelope'], connector_q)
    return dict(status='loaded_candidate_offline_checked_not_live_tested', motion_sent=False,
        execution_enabled=False, slot=1, plate='48-well; long-side grip',
        endpoint=end, endpoint_joints=robot['joints'], observed_axes=capture['native']['external_axes'],
        observed_axes_are_not_new_grip_targets=True,
        source=str(capture_path), source_sha256=hashlib.sha256(capture_path.read_bytes()).hexdigest(),
        parent=str(PARENT), parent_sha256=hashlib.sha256(PARENT.read_bytes()).hexdigest(),
        recording_sha256=hashlib.sha256(raw).hexdigest(), samples=len(rows), valid_samples=len(valid),
        recording_bounds={k:[min(r['robot']['pose_mm'][k] for r in valid),
                             max(r['robot']['pose_mm'][k] for r in valid)] for k in KEYS},
        start=start, points=points, speeds=[137,137,5],
        reverse_points=reverse_points, reverse_speeds=[5,137,137],
        horizontal_insertion_mm=math.dist([entry[k] for k in KEYS[:3]], [end[k] for k in KEYS[:3]]),
        validation=forward, reverse_validation=reverse, transmitted_validation=transmitted,
        proof_to_clearance=dict(start=proof, points=[start], validation=connector),
        config=parent['config'], envelope=parent['envelope'],
        queue_intent='Existing mixed-speed Lua queue; exact horizontal final entry, no corner cut into slot.',
        limitations=['Prior Path A was tested empty with closed jaws, not with a loaded plate.',
                     'IK and envelope checks do not establish rack/plate collision clearance.',
                     'Current controller is disabled/paused with a held plate; no startup or motion dispatched.',
                     'Release, seating and lift-out remain separate untested slot operations.'])


if __name__ == '__main__':
    result = build()
    path = SESSION / 'slot_1_loaded_path_a_candidate_v1.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(record=str(path), endpoint=result['endpoint'], points=result['points'],
                          samples=result['samples'], horizontal_insertion_mm=result['horizontal_insertion_mm'],
                          forward_and_reverse_ik_valid=True, motion_sent=False), indent=2))
