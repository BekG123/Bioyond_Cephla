"""Manual recovery acknowledgment; never dispatches robot commands."""
import hashlib
import json
import math
import time
from uuid import uuid4

from researcher_teaching import TeachingError


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recovered(path):
    """Receipts resolve only the exact original failure, not future attempts."""
    for attempt in path.parent.glob('*.json'):
        try:
            data = json.loads(attempt.read_text(encoding='utf-8'))
            seq = data.get('sequence') or {}
            if (data.get('status') == 'completed' and seq.get('state') == 'done'
                    and (seq.get('result') or {}).get('ok') is True
                    and data.get('recovery_home_verified') is True
                    and data.get('recovery_of', {}).get(path.name) == digest(path)):
                return True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    for receipt in (path.parent / 'manual_recoveries').glob('*.json'):
        try:
            data = json.loads(receipt.read_text(encoding='utf-8'))
            if (data['schema'] == 'cephla.manual-home-recovery.v1'
                    and data['verified_at_home'] is True
                    and data['motion_sent'] is False
                    and data['attempts'].get(path.name) == digest(path)):
                return True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return False


def verify_snapshot(state, target, joints):
    if (not state.get('connected') or not state.get('ok') or state.get('errors')
            or state.get('enabled') is not False
            or state.get('program_state', {}).get('state') != 'stopped'):
        raise TeachingError('Recovery requires a connected, fault-free, disabled and stopped arm.')
    for field, expected, tolerance in (('pose_mm', target, .1), ('joints', joints, .1)):
        for key, value in expected.items():
            actual = state.get(field, {}).get(key)
            if (type(actual) not in (float, int) or not math.isfinite(actual)
                    or not math.isfinite(value) or abs(actual - value) > tolerance):
                raise TeachingError('Manual recovery is not at saved Home pose and joint configuration.')
    e1 = state.get('external_axes', {}).get('E1')
    if type(e1) not in (float, int) or not math.isfinite(e1) or abs(e1) > .1:
        raise TeachingError('Recovery requires an inspected empty, closed gripper.')


def acknowledge(connection, body):
    if (body.get('reviewed_failure') is not True or body.get('empty_gripper') is not True
            or body.get('manual_home_confirmed') is not True
            or not isinstance(body.get('review_notes'), str) or not body['review_notes'].strip()):
        raise TeachingError('Review the failure and confirm manual Home recovery with empty claws; include review notes.')
    home = connection.home
    runner, service = home.get_runner(), home.get_service()
    if runner.active or getattr(runner, 'reserved', False):
        raise TeachingError('Stop all workflows before acknowledging recovery.')
    points_hash = digest(home.path)
    data = json.loads(home.path.read_text(encoding='utf-8-sig'))
    reference = data['points'][data['roles']['home']].get('joint_reference', {})
    if set(reference) != {'J1', 'J2', 'J3', 'J4'}:
        raise TeachingError('Saved Home needs a reviewed joint reference before recovery.')
    target, target_id = home.target()
    expected = body.get('attempts')
    unresolved = connection.unresolved_attempts()
    if not unresolved or expected != unresolved:
        raise TeachingError('Review the current unresolved attempt names and SHA-256 hashes first.')
    snapshots = []
    for _ in range(2):
        state = service.status()
        if home.get_draggo().public(state).get('state') != 'off':
            raise TeachingError('End hand-guiding before acknowledging recovery.')
        verify_snapshot(state, target, reference)
        snapshots.append(state)
    if digest(home.path) != points_hash or connection.unresolved_attempts() != unresolved:
        raise TeachingError('Home or failure evidence changed during recovery review.')
    folder = connection.folder / 'manual_recoveries'
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / (uuid4().hex + '.json')
    record = dict(schema='cephla.manual-home-recovery.v1', at=time.time(),
                  attempts=unresolved, target_id=target_id, points_sha256=points_hash,
                  snapshots=snapshots, review_notes=body['review_notes'].strip(),
                  verified_at_home=True, motion_sent=False)
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
    return dict(ok=True, receipt=str(receipt),
                message='Manual Home recovery recorded. Request a fresh workflow; nothing was enabled or moved.')
