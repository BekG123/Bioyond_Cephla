"""Evidence for Home startup refusals, distinct from uncertain travel."""

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
    return known_startup_refusal(record) or known_preflight_refusal(record)
