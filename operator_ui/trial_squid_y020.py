"""One explicitly approved stage-only Y0.200 trial; never accepts a robot route."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen

from squid_adapter import native_command

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / 'squid_stage_reference.json'
EXPECTED = '8ce112acb6cc50df53319fb9c3354ffe09768db8b99969a72b345a04ce07666a'
TARGET = dict(x_mm=.05, y_mm=.2, z_mm=1.05)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def host(path):
    with urlopen('http://127.0.0.1:5002'+path, timeout=5) as response:
        return json.load(response)


def arm_home_idle():
    state = host('/state')
    agent = host('/researcher/api/lacry/state')
    robot = state['robot']
    if (state['sequence']['active'] or agent.get('busy') or agent.get('pending')
            or agent.get('review') or agent.get('running', {}).get('active')):
        raise RuntimeError('Another workflow or pending interaction exists; trial refused.')
    if not robot.get('connected') or not robot.get('ok') or robot.get('errors'):
        raise RuntimeError('Robot status is unhealthy; no fault reset is permitted.')
    for axis, target in dict(X=289.97, Y=62.63, Z=248.02, Rz=-3.88).items():
        if abs(robot['pose_mm'][axis]-target) > .2:
            raise RuntimeError('Robot is not at Home; trial refused.')
    return robot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-stage-only', action='store_true', required=True)
    parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = ROOT/'reports/squid_stage'/('y020_trial_'+stamp)
    folder.mkdir()
    report = dict(status='preflight', target_mm=TARGET, tolerance_mm=.02,
                  authorization='Approve Y0.200 mm trial—stage clear, E-stop supervised',
                  robot_transfer_authorized=False, events=[])

    def save(event, **data):
        report['events'].append(dict(at=time.time(), event=event, **data))
        temporary = folder/'trial.tmp'
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(folder/'trial.json')
        print(event, json.dumps(data), flush=True)

    original = REFERENCE.read_bytes()
    old = json.loads(original.decode('utf-8-sig'))
    installed = False
    trial = deepcopy(old)
    trial.update(dropoff=TARGET, accepted_for_robot_loading=False,
                 stage_return_verified=False, operator_acceptance=None,
                 revision_authorization=report['authorization'],
                 validation='Approved stage-only trial; robot loading acceptance pending.',
                 source_reference_sha256=EXPECTED)
    trial_hash = digest(trial)
    try:
        if digest(old) != EXPECTED:
            raise RuntimeError('Reference changed since review; no motion sent.')
        (folder/'original_reference.json').write_bytes(original)
        (folder/'trial_reference.json').write_text(json.dumps(trial, indent=2), encoding='utf-8')
        robot = arm_home_idle()
        acquisition = native_command('get_acquisition_status')
        if acquisition.get('in_progress') is not False or acquisition.get('cleanup', {}).get('status') not in ('idle', 'completed', None):
            raise RuntimeError('Acquisition/cleanup is not idle or complete.')
        bridge = native_command('get_stage_reference')
        if (bridge.get('reference_hash') != EXPECTED or bridge.get('controller_serial') != '12769210'
                or bridge.get('stage_simulated') is not False):
            raise RuntimeError('Connected stage/reference differs from approved review.')
        try:
            settings = native_command('get_current_acquisition_settings')
            (folder/'imaging_settings.json').write_text(json.dumps(settings, indent=2), encoding='utf-8')
        except ValueError as error:
            if str(error).strip() != 'Select the wells or imaging locations in Squid first.':
                raise
            save('no_current_sites', reason=str(error), existing_history_preserved=True)
        save('preflight_passed', robot=robot, stage=native_command('get_position'), acquisition=acquisition)
        arm_home_idle()
        if REFERENCE.read_bytes() != original:
            raise RuntimeError('Concurrent reference edit; no motion sent.')
        temporary = REFERENCE.with_suffix('.trial.tmp')
        temporary.write_text(json.dumps(trial, indent=2), encoding='utf-8')
        temporary.replace(REFERENCE)
        installed = True
        # The unchanged experiment protocol disagrees with this temporary target,
        # blocking robot experiment planning during the stage-only trial.
        report['status'] = 'running'
        save('command_requested', command='return_to_recorded_dropoff', reference_hash=trial_hash)
        result = native_command('return_to_recorded_dropoff', {'reference_hash': trial_hash}, timeout=180)
        save('command_result', result=result)
        if result.get('at_dropoff') is not True:
            raise RuntimeError('Native command did not confirm arrival; no retry allowed.')
        measurements = []
        for _ in range(3):
            actual = native_command('get_position')
            delta = {k: actual[k]-TARGET[k] for k in TARGET}
            save('arrival_readback', measured=actual, error_mm=delta)
            if any(abs(value) > .02 for value in delta.values()):
                raise RuntimeError('Arrival outside unchanged 0.020 mm tolerance; no retry allowed.')
            measurements.append(actual)
            time.sleep(.3)
        final_robot = arm_home_idle()
        report.update(status='passed_stage_only', measurements=measurements, final_robot=final_robot,
                      accepted_for_robot_loading=False)
        save('trial_passed', robot_remained_home=True)
    except Exception as error:
        report.update(status='failed_or_uncertain', error=str(error))
        save('trial_stopped', error=str(error), retry_sent=False)
        raise
    finally:
        if installed:
            if digest(json.loads(REFERENCE.read_text(encoding='utf-8-sig'))) != trial_hash:
                save('restore_refused', reason='Concurrent reference change; inspect manually.')
            else:
                temporary = REFERENCE.with_suffix('.restore.tmp')
                temporary.write_bytes(original)
                temporary.replace(REFERENCE)
                save('original_reference_restored', new_reference_acceptance_pending=True)
        print('REPORT', str(folder/'trial.json'), flush=True)


if __name__ == '__main__':
    main()
