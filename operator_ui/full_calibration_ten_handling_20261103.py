"""One calibration followed by ten accepted drop-off/pickup cycles; no retries."""
import argparse
import json
import time
import full_calibration_handling_20261103 as workflow
from proof_lift_plate import api, near, write
from capture_squid_approach_20261103 import FOLDER, sha
from squid_adapter import native_command, SquidAdapter
from squid_execution import at_position

OUT = FOLDER / 'full_calibration_ten_handling_20261103'
AUTH = ('Operator requested one full calibration followed by ten autonomous Squid '
        'drop-off/empty Home/pickup/loaded Home cycles; plate returned to pickup '
        'holder, unchanged accepted setup and existing clearance/supervision. '
        'No imaging, stage movement, automatic retry or controller restart.')
SOURCE = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
HASH = '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81'
LOADING = dict(x_mm=.5000625, y_mm=.5000625, z_mm=.063984375)


def home(opening=None):
    state = api('state')
    r = state['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors')
            or not r.get('enabled') or r['control_mode']['mode'] != 'auto'
            or r['program_state']['state'] != 'running' or state['sequence']['active']):
        raise RuntimeError('Healthy idle running Auto required; no recovery.')
    plan = json.loads(SOURCE.read_bytes())
    near(r['pose_mm'], plan['routes']['from_capture'][0], .1)
    if opening is not None and abs(r['external_axes']['E1'] - opening) > .15:
        raise RuntimeError('Unexpected Home grip feedback')
    env = {k: [state['envelope'][k]['min'], state['envelope'][k]['max']] for k in ('X','Y','Z')}
    if sha(SOURCE) != HASH or not state['envelope']['enabled'] or env != plan['envelope'] or api('robot_params') != plan['cfg']:
        raise RuntimeError('Reviewed route or settings changed')
    return state


def stage_ready():
    state = SquidAdapter(background=False).connect()
    if state.get('stage_simulated') is not False or state['status'] not in ('idle', 'historical', 'completed'):
        raise RuntimeError('Physical Squid must remain idle at loading position')
    position = native_command('get_position')
    at_position(position, LOADING)
    return dict(state=state, position=position)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if OUT.exists():
        raise RuntimeError('Batch already attempted; no replay')
    workflow.OUT, workflow.AUTH = OUT/'calibration', AUTH
    # Same validation entry point as the accepted one-calibration experiment.
    if not args.execute:
        workflow.main(calibration_only=True)
        stage_ready()
        print('Validated one calibration and ten handling cycles; no movement.', flush=True)
        return
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip':'192.168.201.220'})
    initial = home()
    squid = stage_ready()
    OUT.mkdir()
    record = dict(status='running', started_at=time.time(), authorization=AUTH,
                  requested_cycles=10, completed_cycles=0, phase='calibration',
                  initial_state=initial, initial_squid=squid, cycles=[], automatic_retries=False)
    output = OUT/'batch.json'
    write(output, record)
    try:
        workflow.main(calibration_only=True)
        receipt = workflow.OUT/'run.json'
        if json.loads(receipt.read_bytes())['status'] != 'full_calibration_loaded_home_completed_pending_operator_assessment':
            raise RuntimeError('Fresh calibration completion unverified')
        record['calibration_sha256'] = sha(receipt)
        for number in range(1, 11):
            home(3.9)
            stage_ready()
            folder = OUT/f'cycle_{number:02d}'
            folder.mkdir()
            cycle = dict(number=number, started_at=time.time(), status='dropoff_running')
            record['cycles'].append(cycle)
            record.update(current_cycle=number, phase='dropoff')
            write(output, record)
            print(json.dumps(dict(cycle=number, phase='dropoff_started')), flush=True)
            workflow.invoke(workflow.approach, ['--execute'], folder)
            workflow.invoke(workflow.release, ['--execute'], folder, AUTH)
            released = folder/'release_empty_home_20261103.json'
            if json.loads(released.read_bytes())['status'] != 'release_and_empty_home_completed_pending_operator_assessment':
                raise RuntimeError('Drop-off completion unverified')
            home(7)
            stage_ready()
            cycle.update(status='pickup_running', release_sha256=sha(released))
            record['phase'] = 'pickup'
            write(output, record)
            workflow.invoke(workflow.pickup, ['--execute'], folder, AUTH)
            picked = folder/'pickup_home_trial_20261103.json'
            result = json.loads(picked.read_bytes())
            if result['status'] != 'pickup_and_home_completed_pending_operator_assessment' or len(result['steps']) != 8 or any(s['status'] != 'completed' for s in result['steps']):
                raise RuntimeError('Pickup completion unverified')
            final = home(3.9)
            cycle.update(status='completed_pending_operator_assessment', finished_at=time.time(),
                         pickup_sha256=sha(picked), final_robot=final['robot'])
            record['completed_cycles'] = number
            write(output, record)
            print(json.dumps(dict(cycle=number, completed_cycles=number)), flush=True)
        record.update(status='ten_handling_cycles_completed_pending_operator_assessment', final_state=home(3.9))
    except Exception as error:
        record.update(status='stopped_or_failed', error=str(error))
        try:
            record['stop_response'] = api('program', dict(action='stop'))
        except Exception as stop_error:
            record['stop_error'] = str(stop_error)
        raise
    finally:
        record['finished_at'] = time.time()
        write(output, record)
        print(json.dumps(dict(status=record['status'], completed_cycles=record['completed_cycles'], report=str(output))), flush=True)


if __name__ == '__main__':
    main()
