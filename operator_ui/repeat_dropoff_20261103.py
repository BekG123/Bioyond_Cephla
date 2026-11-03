"""One requested repeat of the operator-accepted drop-off and empty return."""
import argparse
import json
import time
import dropoff_approach_20261103 as approach
import release_empty_home_20261103 as release
from capture_squid_approach_20261103 import FOLDER, sha
from prepare_squid_destination import validate
from proof_lift_plate import api, near, write


def main(output_dir=None, pickup_receipt=None, authorization=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    folder = FOLDER / 'dropoff_repeat_02_20261103' if output_dir is None else output_dir
    folder.mkdir(exist_ok=True)
    output = folder / 'trial.json'
    if output.exists():
        raise RuntimeError('Repeat already attempted; no retry')
    previous = json.loads((pickup_receipt or (FOLDER / 'pickup_home_trial_20261103.json')).read_bytes())
    if previous['status'] != 'pickup_and_home_completed_pending_operator_assessment':
        raise RuntimeError('Completed pickup required')
    source = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
    if sha(source) != '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81':
        raise RuntimeError('Route changed')
    plan = json.loads(source.read_bytes())
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip': '192.168.201.220'})
    state = api('state')
    near(state['robot']['pose_mm'], plan['routes']['from_capture'][0], .05)
    if abs(state['robot']['external_axes']['E1'] - previous['final_state']['robot']['external_axes']['E1']) > .1:
        raise RuntimeError('Grip changed since accepted pickup')
    validate(plan['routes']['from_capture'], state['robot']['joints'], plan['cfg'], plan['envelope'])
    authorization = authorization or 'Operator confirmed pickup secure and level and requested repeat drop-off at Squid, using the just-accepted release and empty-return routine.'
    if not args.execute:
        approach.main(folder)
        print('Full route checked; repeat drop-off dry run only.', flush=True)
        return
    record = dict(status='started', at=time.time(), authorization=authorization, source_state=state)
    write(output, record)
    try:
        approach.main(folder)
        release.main(folder, authorization)
        record.update(status='dropoff_repeat_completed_pending_operator_assessment', final_state=api('state'))
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
