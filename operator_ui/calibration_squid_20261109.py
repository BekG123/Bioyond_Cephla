"""Authorized unchanged 48-well pickup and closed-claw Squid delivery."""
import json
import sys
from copy import deepcopy

import full_calibration_handling_20261103 as calibration
import execute_continuous_squid_return_20261103 as travel
from capture_squid_approach_20261103 import FOLDER, sha, save
from squid_handling_route import CURRENT_SOURCE, CURRENT_SHA

OUT = FOLDER / 'calibration_squid_20261109'
PLAN = FOLDER / 'calibration_squid_20261109_plan.json'
AUTH = ('Operator requested full arm calibration and transfer to Squid; confirmed '
        '48-well plate flat in calibration holder, empty gripper, arm released, '
        'pickup/Home/Squid route and hands clear, E-stop supervised, and Squid '
        'holder unchanged from latest successful taught position. Keep plate '
        'gripped at Squid. No release, imaging, return, or automatic retry.')


def main():
    if sha(CURRENT_SOURCE) != CURRENT_SHA:
        raise RuntimeError('Accepted November 8 route changed')
    plan = deepcopy(json.loads(CURRENT_SOURCE.read_bytes()))
    plan.update(operator_intent=AUTH, reviewed_source=str(CURRENT_SOURCE),
                reviewed_source_sha256=CURRENT_SHA,
                completion_status='closed_claw_squid_delivery_complete_pending_operator_assessment')
    if PLAN.exists():
        if json.loads(PLAN.read_bytes()) != plan:
            raise RuntimeError('Run plan changed')
    else:
        save(PLAN, plan)
    calibration.OUT, calibration.AUTH = OUT, AUTH
    calibration.main(calibration_only=True, route_source=CURRENT_SOURCE, route_sha=CURRENT_SHA)
    if '--execute' in sys.argv:
        result = json.loads((OUT / 'run.json').read_bytes())
        if result['status'] != 'full_calibration_loaded_home_completed_pending_operator_assessment':
            raise RuntimeError('Fresh calibration and loaded Home did not complete')
    travel.PLAN, travel.SHA = PLAN, sha(PLAN)
    travel.OUTPUT = OUT / 'squid_transfer.json'
    travel.main(expected_speeds=(137,137,137,5), vertical_legs=(0,3))


if __name__ == '__main__':
    main()
