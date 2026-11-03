"""Finish the requested calibrated closed-claw round trip; no release."""
import json
from copy import deepcopy
import execute_continuous_squid_return_20261103 as runner
from capture_squid_approach_20261103 import FOLDER, sha, save
from proof_lift_plate import api, near


def main():
    folder = FOLDER / 'full_calibration_closed_transfer_20261103'
    forward_path = folder / 'trial.json'
    forward = json.loads(forward_path.read_bytes())
    if forward['status'] != 'calibrated_closed_transfer_completed_pending_operator_assessment' or forward['release_executed']:
        raise RuntimeError('Completed closed-claw forward transfer required')
    source = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
    if sha(source) != '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81':
        raise RuntimeError('Accepted route changed')
    plan = deepcopy(json.loads(source.read_bytes()))
    plan['routes']['from_capture'] = plan['routes']['from_capture'][4:]
    plan['leg_speeds'] = [5, 137, 137, 137]
    plan['completion_status'] = 'calibrated_closed_return_home_completed_pending_operator_assessment'
    plan['operator_intent'] = 'Operator clarified closed-claw transfer includes return Home and instructed continue; retain the plate without claw commands.'
    plan['forward_receipt_sha256'] = sha(forward_path)
    runner.PLAN = folder / 'return_plan.json'
    runner.OUTPUT = folder / 'return_trial.json'
    if runner.PLAN.exists():
        if json.loads(runner.PLAN.read_bytes()) != plan:
            raise RuntimeError('Return plan changed')
    else:
        save(runner.PLAN, plan)
    runner.SHA = sha(runner.PLAN)
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip': '192.168.201.220'})
    state = api('state')
    near(state['robot']['pose_mm'], forward['final_state']['robot']['pose_mm'], .05)
    if abs(state['robot']['external_axes']['E1'] - forward['final_state']['robot']['external_axes']['E1']) > .1:
        raise RuntimeError('Grip changed since forward arrival')
    runner.main(expected_speeds=(5, 137, 137, 137), vertical_legs=(0, 3))


if __name__ == '__main__':
    main()
