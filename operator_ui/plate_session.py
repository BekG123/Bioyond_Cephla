"""HOME fixture / IDLE parking contract and read-only session planning.

No robot commands live here. Old route keys and signed trial files retain their
historical names. The new near-holder rotation must be commissioned separately
from the old holder rotation performed with the arm away at IDLE.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4

from calibration_e2 import accepted as in_precalibration_range

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'Pick and Hold/plate_session_workflow.json'
TEXT_FIELDS = {'summary', 'label', 'labels', 'requirements', 'message', 'step',
               'done', 'blockers', 'station', 'name', 'description', 'reason', 'error', 'handling_note'}


def legacy_text(text):
    """Only call on legacy host text, never researcher/model chat or evidence."""
    return re.sub(r'\bHome\b', 'IDLE', text)


def public_labels(value, field=''):
    if isinstance(value, dict):
        if value.get('location_schema') == 2:
            return deepcopy(value)
        return {k: public_labels(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [public_labels(v, field) for v in value]
    return legacy_text(value) if isinstance(value, str) and field in TEXT_FIELDS else value


def configuration():
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    reference = json.loads((ROOT / config['destinations']['Hamilton']['reference']).read_bytes())
    target = config['destinations']['Hamilton']['target_degrees']
    if not math.isfinite(target) or abs(target-reference['settings']['holder_e2_degrees']) > 1e-9:
        raise ValueError('Hamilton holder target differs from the accepted short-side reference.')
    if config['destinations']['Hamilton']['target_e1_mm'] != reference['settings']['target_e1_mm']:
        raise ValueError('Hamilton grip differs from the accepted short-side reference.')
    long_side = json.loads((ROOT/'Pick and Hold/Grip/accepted_48well_grip_reference.json').read_bytes())
    if config['destinations']['Squid']['target_e1_mm'] != long_side['settings']['target_e1_mm']:
        raise ValueError('Squid grip differs from the accepted 48-well long-side reference.')
    return config


def setup_digest():
    """Bind calibration reuse to setup files, not old run success messages."""
    paths = [CONFIG, ROOT/'operator_ui/e2_reference.json',
             ROOT/'Pick and Hold/Calibration/plate_48_pickup_profile.json',
             ROOT/'Pick and Hold/Grip/short_side_48well_reference.json',
             ROOT/'Pick and Hold/Grip/accepted_48well_grip_reference.json',
             ROOT/'Pick and Hold/Grip/accepted_descent_endpoint.json',
             ROOT/'operator_ui/robot_params.json',
             ROOT/'operator_ui/points.json']
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class CalibrationSession:
    """Process-local: a restart never inherits motion authority or calibration."""
    def __init__(self):
        self.id = uuid4().hex
        self.receipt = None
        self.invalid_reason = 'Full calibration has not completed in this session.'

    def invalidate(self, reason):
        self.receipt = None
        self.invalid_reason = reason

    def complete(self, *, run_id, result, setup):
        if not run_id or result.get('ok') is not True:
            raise ValueError('Verified full-calibration completion is required.')
        self.receipt = dict(run_id=run_id, setup=setup, at=time.time())
        self.invalid_reason = ''

    def public(self, setup=None):
        if self.receipt and setup is not None and setup != self.receipt['setup']:
            self.invalidate('Setup changed; full calibration is needed again.')
        return dict(session_id=self.id, calibrated=self.receipt is not None,
                    evidence=deepcopy(self.receipt), reason=self.invalid_reason)


def verify_rotation_clearance(observation, *, seated_z, now=None):
    """Validation for the future commissioning adapter; no motion or retry.

The adapter must supply fresh measured feedback plus the operator's seating
and full-sweep observation. An E1 position alone cannot establish release.
"""
    now = time.time() if now is None else now
    for key in ('at', 'z_mm', 'e1_mm', 'e2_degrees', 'lift_from_seated_mm'):
        if not isinstance(observation.get(key), (int, float)) or not math.isfinite(observation[key]):
            raise ValueError('Missing or invalid '+key)
    if not 0 <= now-observation['at'] <= 2:
        raise ValueError('Fresh stationary feedback is required.')
    for key in ('stationary', 'plate_supported', 'plate_released', 'sweep_reviewed',
                'hands_clear', 'estop_supervised', 'path_checked'):
        if observation.get(key) is not True:
            raise ValueError('Rotation requires '+key)
    if observation.get('payload') != 'empty' or observation.get('fault') is not False:
        raise ValueError('Do not rotate with a held plate or uncertain controller state.')
    if observation.get('timeout') is not False:
        raise ValueError('Unknown or timed-out motion must not be retried.')
    clearance = configuration()['holder_clearance']
    if abs(observation['e1_mm']-clearance['open_mm']) > clearance['opening_tolerance_mm']:
        raise ValueError('Open E1 to 28 mm before rotation.')
    if (not math.isfinite(seated_z) or
        abs(observation['z_mm']-seated_z-clearance['lift_mm']) > clearance['lift_tolerance_mm'] or
        abs(observation['lift_from_seated_mm']-clearance['lift_mm']) > clearance['lift_tolerance_mm']):
        raise ValueError('Verify the 5 mm release-first lift before rotation.')
    return True


def verify_holder(destination, samples, *, now=None):
    now = time.time() if now is None else now
    config = configuration()
    if destination not in config['destinations'] or len(samples) < 3:
        raise ValueError('Choose a destination and provide three fresh holder readings.')
    target = config['destinations'][destination]
    previous_at = None
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('Timestamped holder feedback is required.')
        value, at = sample.get('degrees'), sample.get('at')
        if (not isinstance(at, (int, float)) or not math.isfinite(at)
                or not 0 <= now-at <= 2 or (previous_at is not None and at <= previous_at)):
            raise ValueError('Three distinct fresh holder readings are required.')
        previous_at = at
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Invalid holder reading.')
        if destination == 'Squid':
            accepted = in_precalibration_range(value)
        else:
            accepted = abs(value-target['target_degrees']) <= target['tolerance_degrees']
        if not accepted:
            raise ValueError('Holder angle does not match the '+destination+' grip reference.')
    return True


def preview(destination, session, *, home_only=False):
    config = configuration()
    if destination not in config['destinations'] and not home_only:
        raise ValueError('Choose Hamilton or Squid as the first destination.')
    blockers = [config['execution']['reason']]
    if not session.get('calibrated'):
        # Surface the live source's acceptance state; never resurrect an old
        # successful grip for a subsequently adjusted endpoint.
        profile = json.loads((ROOT/'Pick and Hold/Calibration/plate_48_pickup_profile.json').read_bytes())
        if (profile.get('physical_grip_validated_for_plate') is not True
                or not profile.get('accepted_grip_reference')
                or not profile.get('accepted_grip_reference_sha256')):
            blockers.append('The active 48-well pickup profile has no accepted grip binding for its current endpoint. Review that reference before full calibration/pickup.')
    steps = []
    def step(state, label, **data):
        steps.append(dict(kind='plate_session', state=state, label=label, **data))
    if not session.get('calibrated'):
        step('CALIBRATING', 'Calibrate, align, descend, grip and lift 5 mm at speed 5')
        step('HOME_SEATED', 'Lower those 5 mm at speed 5 into the unchanged supporting HOME holder')
        step('HOME_RELEASED', 'Open E1 to 28 mm while the plate rests in HOME')
    step('HOME_CLEAR', 'Verify the empty arm 30 mm above HOME, with E1 open to 28 mm; verify the full sweep',
         lift_mm=30, lift_speed=137, open_e1_mm=28)
    rotation = None
    if not home_only:
        rotation = deepcopy(config['destinations'][destination])
        if destination == 'Hamilton':
            step('HOME_ORIENTED', 'Rotate the released holder to the taught absolute E2 90.717 degrees',
                 target_e2_degrees=rotation['target_degrees'], relative_rotation=False)
        else:
            step('HOME_ORIENTED', 'Verify the original holder orientation; do not rotate',
                 target_e2_degrees=1.77, rotate=False)
        step('HOME_VERIFIED', 'Verify three fresh holder-angle readings before re-gripping')
        step('HOME_GRIPPED', 'Re-grip using the accepted '+destination+' plate profile',
             target_e1_mm=rotation['target_e1_mm'])
        step('PICKUP_VERIFIED', 'Lift 5 mm slowly and verify plate retention')
        step('IN_TRANSIT', 'Follow the reviewed route to '+destination+'; retain the slower final approach')
    return dict(location_schema=2, id=uuid4().hex, at=time.time(), dispatch='plate_session_preview',
                executable=False, actions=['plate_session'], labels=['HOME plate preparation'],
                summary=('Place the plate at HOME.' if home_only else
                         ('Reuse this session calibration, ' if session.get('calibrated') else 'Calibrate once, ')
                         +'prepare the plate at HOME, then carry it to '+destination+'.'),
                steps=steps, rotation=rotation, first_destination=None if home_only else destination,
                session=deepcopy(session), configuration_sha256=hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
                blockers=blockers,
                requirements=['The plate is supported before release; never rotate a held plate.',
                    'Verify the new release and 30 mm empty-arm clearance plus the full holder/plate/jaw sweep in the first supervised trial.',
                    'Keep hands clear and supervise the E-stop for every motion.',
                    'Check the envelope, IK, arrival and grip; stop on faults, uncertainty or timeouts. No automatic retry.'])


RULES = '''
Current robot location contract (supersedes historical Home naming):
IDLE is the former true Home parking pose. HOME is the calibration holder,
not the old parking pose and not a single universal TCP coordinate.
Use move_idle for the old parking route. move_home plans Cellvis empty-arm
recovery from either accepted HOME clearance: restore the released holder to
1.77 degrees, then use the accepted short-to-long clearance connector if needed.
It requires current confirmation of empty jaws and a seated lid-off Cellvis
P24-1.5H-N plate; do not infer these from encoder readings. It never calibrates,
descends, grips, restarts the controller or resumes an experiment. Unknown
positions remain refused; never substitute the legacy parking route.
For the new experiment/session departure call plan_plate_session with the first
destination Hamilton or Squid. Ask which if unspecified. Calibrate once per
valid session: grip and lift 5 mm at speed 5, lower those 5 mm at speed 5 into
the unchanged HOME holder, open E1 to 28 mm, then raise the EMPTY arm 30 mm
at speed 137. Full calibration ends there with the plate in HOME, not at IDLE.
Only then separately verify clearance, orient the holder, verify E2 and re-grip.
Hamilton uses absolute E2=90.71661229181757 degrees (about 90.717),
NOT current angle plus 90. Squid uses the original E2=1.77 degrees and the
accepted monitoring range 1.740<=E2<=1.82, with no rotation. Calibration
still corrects toward E2=1.77 using its original correction threshold.
Never rotate while held. Grip profiles differ: Hamilton short side E1=25 mm;
Squid long side uses the accepted 48-well profile, not the two-disk grip.
The new 48-well session workflow is prepared, not physically commissioned. Report
its trial blocker plainly; do not substitute old travel to bypass the new steps.
An experiment preview is not an executed run. Do not infer plate security from
an E1 reading or a cached calibration success. Native microscope/Hamilton homing
names and archived controller route keys are unchanged.
If the researcher requests a new session or reports a physically moved fixture,
call begin_plate_session with the reason. This invalidates only calibration
reuse; it does not clear faults or uncertain motion history.
'''
