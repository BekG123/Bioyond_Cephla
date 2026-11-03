"""One confirmed release followed by the tested continuous-lift Home route."""
import argparse
import json
import sys
import time
from copy import deepcopy
import execute_continuous_squid_return_20261103 as runner
from capture_squid_approach_20261103 import FOLDER, sha, save
from proof_lift_plate import api, near, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    output = FOLDER / 'release_empty_home_20261103.json'
    if output.exists():
        raise RuntimeError('Already attempted; no automatic retry')
    source = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
    if sha(source) != '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81':
        raise RuntimeError('Reviewed route changed')
    approach = FOLDER / 'dropoff_approach_trial_20261103.json'
    receipt = json.loads(approach.read_bytes())
    if receipt['status'] != 'at_squid_awaiting_supported_plate_confirmation':
        raise RuntimeError('Completed approach required')
    plan = deepcopy(json.loads(source.read_bytes()))
    plan['routes']['from_capture'] = plan['routes']['from_capture'][4:]
    plan['leg_speeds'] = [5, 137, 137, 137]
    plan['completion_status'] = 'empty_home_completed_pending_operator_assessment'
    plan['operator_intent'] = 'Operator confirmed plate supported and claws clear; release to 7 mm then continuous lift and empty Home.'
    runner.PLAN = FOLDER / 'empty_return_plan_20261103.json'
    runner.OUTPUT = FOLDER / 'empty_return_trial_20261103.json'
    if runner.PLAN.exists():
        if json.loads(runner.PLAN.read_bytes()) != plan:
            raise RuntimeError('Plan changed')
    else:
        save(runner.PLAN, plan)
    runner.SHA = sha(runner.PLAN)
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip': '192.168.201.220'})
    # Validate the entire return before any release command.
    original_args = sys.argv[:]
    try:
        sys.argv = [__file__]
        runner.main(vertical_legs=(0, 3))
    finally:
        sys.argv = original_args
    seat = plan['routes']['from_capture'][0]

    def seated():
        state = api('state')
        r = state['robot']
        if not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled') or r['control_mode']['mode'] != 'auto' or r['program_state']['state'] != 'running' or state['sequence']['active']:
            raise RuntimeError('Controller not ready; no recovery')
        near(r['pose_mm'], seat, .1)
        if api('robot_params') != plan['cfg'] or sha(runner.PLAN) != runner.SHA:
            raise RuntimeError('Settings changed')
        return state

    initial = seated()
    if abs(initial['robot']['external_axes']['E1'] - receipt['preserved_e1_mm']) > .1:
        raise RuntimeError('Grip changed since arrival')
    if not args.execute:
        print('Validated release to 7 mm at speed 5, then empty Home; no movement.')
        return
    record = dict(status='release_requested', at=time.time(), source_state=initial,
                  operator_confirmation='yes, drop-off', approach_sha256=sha(approach),
                  command=dict(action='move', e1=7, speed=5), release_samples=[])
    write(output, record)
    try:
        response = api('gripper', record['command'])
        record['release_response'] = response
        write(output, record)
        if not response.get('ok') or response.get('recovered'):
            raise RuntimeError('Uncertain release response; no lift')
        for _ in range(3):
            time.sleep(.25)
            state = seated()
            record['release_samples'].append(state)
            if abs(state['robot']['external_axes']['E1'] - 7) > .15:
                raise RuntimeError('Release not settled; no lift')
        record['status'] = 'release_verified'
        write(output, record)
        print('Release verified at 7 mm; starting continuous lift and empty Home.', flush=True)
        runner.main(vertical_legs=(0, 3))
        record.update(status='release_and_empty_home_completed_pending_operator_assessment',
                      return_receipt=str(runner.OUTPUT), return_sha256=sha(runner.OUTPUT))
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
        print(json.dumps(dict(status=record['status'], report=str(output))), flush=True)


if __name__ == '__main__':
    main()
