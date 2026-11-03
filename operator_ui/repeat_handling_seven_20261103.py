"""Seven pickup/Home/drop-off/Home cycles, sequential and without retries."""
import argparse
import json
import time
import pickup_squid_home_20261103 as pickup
import repeat_dropoff_20261103 as dropoff
from capture_squid_approach_20261103 import FOLDER, sha
from prepare_squid_destination import validate
from proof_lift_plate import api, near, write

BATCH = FOLDER / 'handling_seven_20261103'
AUTH = 'Operator accepted pickup and drop-off, confirmed plate seated, and requested seven repetitions of the same handling sequence.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if BATCH.exists():
        raise RuntimeError('Batch already attempted; no replay')
    source = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
    digest = '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81'
    if sha(source) != digest:
        raise RuntimeError('Reviewed route changed')
    plan = json.loads(source.read_bytes())
    previous = FOLDER / 'dropoff_repeat_02_20261103/trial.json'
    if json.loads(previous.read_bytes())['status'] != 'dropoff_repeat_completed_pending_operator_assessment':
        raise RuntimeError('Completed prior drop-off required')
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip': '192.168.201.220'})

    def home(opening):
        state = api('state')
        r = state['robot']
        if not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled') or r['control_mode']['mode'] != 'auto' or r['program_state']['state'] != 'running' or state['sequence']['active']:
            raise RuntimeError('Controller not ready; no recovery')
        near(r['pose_mm'], plan['routes']['from_capture'][0], .1)
        if abs(r['external_axes']['E1'] - opening) > .15 + 1e-9:
            raise RuntimeError('Unexpected Home grip feedback')
        env = {k: [state['envelope'][k]['min'], state['envelope'][k]['max']] for k in ('X', 'Y', 'Z')}
        if not state['envelope']['enabled'] or env != plan['envelope'] or api('robot_params') != plan['cfg'] or sha(source) != digest:
            raise RuntimeError('Reviewed settings changed')
        return state

    initial = home(7)
    validate(plan['routes']['from_capture'], initial['robot']['joints'], plan['cfg'], plan['envelope'])
    print(json.dumps(dict(cycles=7, execute=args.execute, sequence='pickup, loaded Home, drop-off, empty Home', transit_speed=137, local_speed=5)), flush=True)
    if not args.execute:
        return
    BATCH.mkdir()
    output = BATCH / 'batch.json'
    record = dict(status='running', at=time.time(), requested_cycles=7, completed_cycles=0,
                  authorization=AUTH, prior_dropoff_sha256=sha(previous), plan_sha256=digest,
                  initial_state=initial, automatic_retries=False, cycles=[])
    write(output, record)
    try:
        for number in range(1, 8):
            home(7)
            folder = BATCH / f'cycle_{number:02d}'
            folder.mkdir()
            cycle = dict(number=number, status='pickup_running', at=time.time())
            record['cycles'].append(cycle)
            record['current_cycle'] = number
            write(output, record)
            print(json.dumps(dict(cycle=number, phase='pickup_started', completed=record['completed_cycles'])), flush=True)
            pickup.main(folder, AUTH)
            receipt = folder / 'pickup_home_trial_20261103.json'
            picked = json.loads(receipt.read_bytes())
            if picked['status'] != 'pickup_and_home_completed_pending_operator_assessment' or len(picked['steps']) != 8 or any(s['status'] != 'completed' for s in picked['steps']):
                raise RuntimeError('Pickup completion unverified')
            home(3.9)
            cycle.update(status='dropoff_running', pickup_receipt=str(receipt), pickup_sha256=sha(receipt))
            write(output, record)
            print(json.dumps(dict(cycle=number, phase='pickup_home_completed_dropoff_started')), flush=True)
            dropoff.main(folder, receipt, AUTH)
            dropped_path = folder / 'trial.json'
            if json.loads(dropped_path.read_bytes())['status'] != 'dropoff_repeat_completed_pending_operator_assessment':
                raise RuntimeError('Drop-off completion unverified')
            final = home(7)
            cycle.update(status='completed_pending_operator_assessment', finished_at=time.time(),
                         dropoff_receipt=str(dropped_path), dropoff_sha256=sha(dropped_path), final_robot=final['robot'])
            record['completed_cycles'] = number
            write(output, record)
            print(json.dumps(dict(cycle=number, status='completed', completed_cycles=number)), flush=True)
        record.update(status='seven_handling_cycles_completed_pending_operator_assessment', final_state=home(7))
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
