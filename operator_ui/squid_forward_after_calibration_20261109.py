"""Repeat accepted November 8 forward travel, keeping the confirmed plate held."""
import json
import sys
import time
from copy import deepcopy
import execute_continuous_squid_return_20261103 as travel
from proof_lift_plate import api, write

SOURCE = travel.FOLDER / 'final_squid_candidate_20261108.json'
SOURCE_SHA = '9805c608b92e8efcd2c046f5f06b50d79b63d7ae61ee95dcb6c948af6050d3ff'
OUT = travel.FOLDER / 'squid_forward_after_calibration_20261109'
CALIBRATION = travel.FOLDER / 'full_calibration_previous_e2_20261109/run.json'
AUTH = ('Operator confirmed the plate remained level without slipping through '
        'the current calibration pickup and loaded Home, then requested travel '
        'to Squid using the recent successful path. Previously confirmed unchanged '
        'Squid holder, clear route, hands clear and E-stop supervision apply. '
        'Forward only, preserve grip, no release or automatic retry.')

if __name__ == '__main__':
    assert not OUT.exists(), 'Attempt already recorded'
    assert travel.sha(SOURCE) == SOURCE_SHA, 'Accepted route changed'
    cal = json.loads(CALIBRATION.read_bytes())
    assert cal['status'] == 'full_calibration_loaded_home_completed_pending_operator_assessment'
    assert api('researcher/api/status')['hand_guiding']['state'] == 'off'
    assert not api('researcher/api/lacry/state')['running']['active']
    travel.PLAN, travel.SHA = SOURCE, SOURCE_SHA
    travel.OUTPUT = OUT / 'transfer.json'
    arguments = sys.argv[:]
    sys.argv = [__file__]
    travel.main(expected_speeds=(137,137,137,5), vertical_legs=(0,3))
    sys.argv = arguments
    if '--execute' in arguments:
        OUT.mkdir()
        write(OUT/'calibration_operator_acceptance.json', {
            'at':time.time(), 'calibration':str(CALIBRATION),
            'calibration_sha256':travel.sha(CALIBRATION),
            'operator_response':'Yes, it did.',
            'observation':'Plate stayed level without slipping through lift and Home return',
            'authorization':AUTH})
        plan = deepcopy(json.loads(SOURCE.read_bytes()))
        plan['operator_intent'] = AUTH
        plan['completion_status'] = 'loaded_squid_forward_completed_pending_operator_assessment'
        plan['source_plan_sha256'] = SOURCE_SHA
        travel.PLAN = OUT/'plan.json'
        write(travel.PLAN, plan)
        travel.SHA = travel.sha(travel.PLAN)
        travel.main(expected_speeds=(137,137,137,5), vertical_legs=(0,3))
