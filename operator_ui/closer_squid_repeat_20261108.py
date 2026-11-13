"""Repeat calibration and the newly tested closed-claw Squid transfer."""
import json
import sys
from closer_squid_teaching_trial_20261107 import trial

trial.OUT = trial.FOLDER / 'calibration_closer_squid_repeat_20261108'

if __name__ == '__main__':
    trial.prepare()
    if '--execute' in sys.argv:
        trial.calibration.OUT = trial.OUT
        trial.calibration.AUTH = trial.AUTH + ' Operator returned plate to pickup holder and arm near Home, requesting this repeat.'
        trial.calibration.main(calibration_only=True)
        result = json.loads((trial.OUT / 'run.json').read_bytes())
        if result['status'] != 'full_calibration_loaded_home_completed_pending_operator_assessment':
            raise RuntimeError('Fresh calibration did not complete')
        trial.travel.PLAN = trial.PLAN
        trial.travel.SHA = trial.sha(trial.PLAN)
        trial.travel.OUTPUT = trial.OUT / 'new_destination_transfer.json'
        trial.travel.main(expected_speeds=(137,137,137,5), vertical_legs=(0,3))
