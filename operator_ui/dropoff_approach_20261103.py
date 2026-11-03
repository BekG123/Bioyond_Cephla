"""Tested forward travel only; stop before releasing the plate."""
import json
from copy import deepcopy
import execute_continuous_squid_return_20261103 as runner
from capture_squid_approach_20261103 import FOLDER, sha, save
from proof_lift_plate import api


def main():
    source = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
    if sha(source) != '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81':
        raise RuntimeError('Accepted route changed')
    plan = deepcopy(json.loads(source.read_bytes()))
    plan['routes']['from_capture'] = plan['routes']['from_capture'][:5]
    plan['leg_speeds'] = [137, 137, 137, 5]
    plan['completion_status'] = 'at_squid_awaiting_supported_plate_confirmation'
    plan['operator_intent'] = 'Operator requested drop-off using tested travel; stop at seat before release for support confirmation.'
    runner.PLAN = FOLDER / 'dropoff_approach_plan_20261103.json'
    runner.OUTPUT = FOLDER / 'dropoff_approach_trial_20261103.json'
    if runner.PLAN.exists():
        if json.loads(runner.PLAN.read_bytes()) != plan:
            raise RuntimeError('Trial plan changed')
    else:
        save(runner.PLAN, plan)
    runner.SHA = sha(runner.PLAN)
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip': '192.168.201.220'})
    runner.main(expected_speeds=(137, 137, 137, 5), vertical_legs=(0, 3))


if __name__ == '__main__':
    main()
