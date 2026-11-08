"""One loaded reverse of the operator-accepted final Squid approach."""
import json
import execute_continuous_squid_return_20261103 as runner
from capture_squid_approach_20261103 import FOLDER, sha, save
from proof_lift_plate import api, near

def main():
    source = FOLDER / 'final_squid_candidate_20261108.json'
    if sha(source) != '9805c608b92e8efcd2c046f5f06b50d79b63d7ae61ee95dcb6c948af6050d3ff':
        raise RuntimeError('Final route changed')
    receipt = FOLDER / 'calibration_final_squid_retry02_20261108/new_destination_transfer.json'
    result = json.loads(receipt.read_bytes())
    if (result['status'] != 'new_squid_destination_reached_pending_operator_assessment'
            or result['plan_sha256'] != sha(source)):
        raise RuntimeError('Matching successful forward trial required')
    plan = json.loads(source.read_bytes())
    state = api('state')
    near(state['robot']['pose_mm'], plan['routes']['from_capture'][-1], .05)
    if abs(state['robot']['external_axes']['E1'] - 3.9) > .15:
        raise RuntimeError('Grip changed; inspect before return')
    if api('researcher/api/status')['hand_guiding']['state'] != 'off':
        raise RuntimeError('Hand-guiding must be off')
    plan['routes']['from_capture'] = list(reversed(plan['routes']['from_capture']))
    plan['leg_speeds'] = [5,137,137,137]
    plan['operator_intent'] = ('Operator confirmed plate level and correctly seated at final destination '
                               'and requested taking it back. Retain plate, preserve claws; '
                               'one continuous lift to Z291.24 then reverse transit to Home.')
    plan['forward_receipt'] = str(receipt)
    plan['forward_receipt_sha256'] = sha(receipt)
    plan['completion_status'] = 'final_squid_loaded_home_completed_pending_operator_assessment'
    runner.PLAN = FOLDER / 'final_squid_loaded_return_20261108_plan.json'
    runner.OUTPUT = FOLDER / 'final_squid_loaded_return_20261108_trial.json'
    if runner.PLAN.exists():
        if json.loads(runner.PLAN.read_bytes()) != plan:
            raise RuntimeError('Return plan changed')
    else:
        save(runner.PLAN, plan)
    runner.SHA = sha(runner.PLAN)
    runner.main(expected_speeds=(5,137,137,137), vertical_legs=(0,3))

if __name__ == '__main__':
    main()
