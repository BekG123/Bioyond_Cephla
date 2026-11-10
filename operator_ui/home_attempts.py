"""Evidence for Home startup refusals, distinct from uncertain travel."""
import hashlib
import json

# Individually reviewed historical records only. This failure occurred during
# first-batch prepare_points, before queue dispatch; original record is retained.
# Review: reports/ik_home/shape_refusal_1793520304775515000_review.md
REVIEWED_NO_TRAVEL = frozenset({
    # Nov 7 first-queue shape rejection; no upload. See shape_refusal_1794117932.json.
    '50726d14711f5c8c2fc8e7a95e74388033aa3f778e0e820faa517ffc3ff4cb5e',
    # Exact Nov 3 first-batch prepare_points rejection before queue upload.
    # See reports/home_attempt_reviews/shape_refusal_1793729692.json.
    '18f32af8b7d6e9d3808659e9612c76f7311158ae32df54a33ce8d96d6c5e06b3',
    # Exact first-batch shape refusal; see reports/home_attempt_reviews/shape_refusal_1793535738.json.
    'b7be3d64972500de8fa8500f1b3f08d05a2244df841f57637f6991859293e67a',
    '0fcbc1f571054ffbd3b760395f157156d676c48eae4afdb83cddfff29b4c60eb',
    '788a0085973ab404c6d30bbd95ca65300ec1dbc97604174b91d905ff529c296c',
    '3786f4965927f66e4cd5f4ed209bf275ef84e62818d837c49f23fe4f14a0964d',
})


def known_reviewed_no_travel(record):
    if not isinstance(record, dict):
        return False
    try:
        raw = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError):
        return False
    return hashlib.sha256(raw).hexdigest() in REVIEWED_NO_TRAVEL

START_REFUSED = 'gripper_held_start_refused'
START_MESSAGE = (
    'Home travel did not start. The last gripper measurement suggested a held plate, '
    'so program startup was refused because it can close the jaws. '
    'Have the operator check the plate and gripper state in Developer view before '
    'requesting a fresh Home plan. A controller reset does not resolve this record.'
)
UNCERTAIN_MESSAGE = (
    'The previous IK Home return has no verified completion or proof that travel '
    'never started. A developer must review its motion log and the current arm '
    'position before another return. Resetting the controller does not resolve '
    'this saved attempt.'
)


class ProgramStartRefused(RuntimeError):
    """Raised only for an explicit refusal before sending program-start."""


class HomeTravelNotStarted(RuntimeError):
    def __init__(self, diagnostic):
        super().__init__(START_MESSAGE)
        self.evidence = dict(schema=1, reason=START_REFUSED,
                             program_start_sent=False, home_travel_dispatched=False,
                             diagnostic=str(diagnostic))


def known_startup_refusal(record):
    """Fail closed: neither a generic failure nor a missing marker is evidence."""
    if not isinstance(record, dict):
        return False
    if record.get('status') not in ('failed_or_stopped', 'stopped_or_failed'):
        return False
    evidence = record.get('home_startup_refusal')
    return (isinstance(evidence, dict) and evidence.get('schema') == 1
            and evidence.get('reason') == START_REFUSED
            and evidence.get('program_start_sent') is False
            and evidence.get('home_travel_dispatched') is False)


def known_preflight_refusal(record):
    if not isinstance(record, dict) or record.get('status') != 'failed_to_start':
        return False
    evidence = record.get('home_preflight_refusal')
    return (isinstance(evidence, dict) and evidence.get('schema') == 1
            and evidence.get('reason') == 'home_preflight_rejected'
            and evidence.get('runner_start_called') is False
            and evidence.get('home_travel_dispatched') is False)


def known_no_travel(record):
    return known_startup_refusal(record) or known_preflight_refusal(record) or known_reviewed_no_travel(record)
