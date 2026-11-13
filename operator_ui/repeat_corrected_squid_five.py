"""Explicitly requested dropoff/pickup cycles; no retries or startup."""
import argparse
import hashlib
import json
import sys
import time
from uuid import uuid4
import test_squid_destination_empty as transfer
import run_accepted_squid_roundtrip as handling
from prepare_squid_destination import validate

SOURCE = transfer.SOURCE.with_name('destination_leveled_20261101T103159Z.json')
SHA = '255f431bf8eef3c100f9f163603d656fe666d9e825683f8d0f9e54850710047e'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--transit-speed', type=int, choices=(40,137), default=40)
    parser.add_argument('--cycles', type=int, choices=(5,10), default=5)
    args = parser.parse_args()
    transfer.SOURCE = handling.SOURCE = SOURCE
    transfer.SHA = handling.SHA = SHA
    speed_args = ['--transit-speed', str(args.transit_speed)]
    sys.argv = [__file__, '--loaded-forward-only', *speed_args]
    transfer.main()  # Existing live readiness, grip, pose and configuration checks.
    candidate = json.loads(SOURCE.read_bytes())
    state = transfer.api('state')
    checked = validate(candidate['routes']['forward'], state['robot']['joints'], candidate['cfg'], candidate['envelope'])
    validate(candidate['routes']['reverse'], checked['final_joints'], candidate['cfg'], candidate['envelope'])
    if not args.execute:
        return
    output = SOURCE.with_name('repeatability_' + str(args.cycles) + '_' + uuid4().hex + '.json')
    record = dict(status='running', started_at=time.time(), planned_cycles=args.cycles, completed_cycles=0,
                  candidate=str(SOURCE), candidate_sha256=SHA,
                  authorization=f'Operator explicitly requested {args.cycles} loaded delivery, release, empty Home, pickup and loaded Home cycles on the corrected Squid route.',
                  initial_state=state, cycles=[], automatic_retries=False, transit_speed=args.transit_speed,
                  grip_position_tolerance_mm=handling.GRIP_POSITION_TOLERANCE_MM,
                  physical_repeatability_acceptance='pending_operator_observation')

    def save():
        output.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')

    def run_stage(module, argv, pattern):
        existing = set(SOURCE.parent.glob(pattern))
        sys.argv = [module.__file__, *argv]
        try:
            module.main()
        finally:
            files = set(SOURCE.parent.glob(pattern))-existing
            cycle['artifacts'].extend(dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(files))
            save()

    save()
    print(json.dumps({'batch_record': str(output), 'cycles': args.cycles}), flush=True)
    try:
        for number in range(1, args.cycles + 1):
            cycle = dict(number=number, status='running', started_at=time.time(), artifacts=[])
            record['cycles'].append(cycle)
            save()
            print(json.dumps({'cycle': number, 'phase': 'loaded_delivery_start'}), flush=True)
            run_stage(transfer, ['--execute', '--loaded-forward-only', *speed_args], 'loaded_trial_*.json')
            # The operator authorized releases and pickups for all five cycles.
            print(json.dumps({'cycle': number, 'phase': 'dropoff_empty_home_pickup_loaded_home'}), flush=True)
            run_stage(handling, ['--execute', *speed_args], 'roundtrip_*.json')
            cycle.update(status='completed_pending_operator_inspection', finished_at=time.time(), final_robot=transfer.api('state')['robot'])
            record['completed_cycles'] = number
            save()
            print(json.dumps({'cycle': number, 'status': 'completed', 'e1': cycle['final_robot']['external_axes']['E1']}), flush=True)
        record['status'] = 'all_cycles_completed_pending_operator_inspection'
    except Exception as error:
        record.update(status='stopped_or_failed', error=str(error))
        cycle.update(status='stopped_or_failed', error=str(error))
        try:
            record['stop_response'] = transfer.api('program', {'action': 'stop'})
        except Exception as stop_error:
            record['stop_error'] = str(stop_error)
        raise
    finally:
        record['finished_at'] = time.time()
        save()
        print(json.dumps({'batch_record': str(output), 'status': record['status'], 'completed_cycles': record['completed_cycles']}), flush=True)


if __name__ == '__main__':
    main()
