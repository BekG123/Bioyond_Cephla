"""Authorized empty return after separate supported release; no jaw commands."""
import json
import execute_continuous_squid_return_20261103 as runner
from capture_squid_approach_20261103 import FOLDER, sha, save
from proof_lift_plate import api


def main():
    source = FOLDER/'closed_claw_roundtrip_plan_20261103.json'
    if sha(source) != '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81':
        raise RuntimeError('Accepted route changed')
    state = api('state')
    if not state['robot'].get('connected'):
        api('connect', {'ip':'192.168.201.220'})
        state = api('state')
    if abs(state['robot']['external_axes']['E1']-7) > .15:
        raise RuntimeError('Expected open empty claws')
    plan = json.loads(source.read_bytes())
    plan['routes']['from_capture'] = plan['routes']['from_capture'][4:]
    plan['leg_speeds'] = [5,137,137,137]
    plan['operator_intent'] = 'Operator confirmed release and requested empty Home only. Preserve open claws; no imaging or further cycles.'
    plan['completion_status'] = 'empty_home_completed_pending_operator_assessment'
    runner.PLAN = FOLDER/'empty_home_after_release_20261107_plan.json'
    runner.OUTPUT = FOLDER/'empty_home_after_release_20261107_trial.json'
    if runner.PLAN.exists():
        if json.loads(runner.PLAN.read_bytes()) != plan:
            raise RuntimeError('Prepared plan changed')
    else:
        save(runner.PLAN, plan)
    runner.SHA = sha(runner.PLAN)
    runner.main(vertical_legs=(0,3))


if __name__ == '__main__':
    main()
