"""Fresh calibration then closed-claw transfer to the final taught destination."""
import json
import sys
import new_squid_teaching_trial_20261107 as trial

trial.CAPTURE = trial.FOLDER / 'taught_final_squid_20261108T083124395256Z.json'
trial.PLAN = trial.FOLDER / 'final_squid_candidate_20261108.json'
trial.OUT = trial.FOLDER / 'calibration_final_squid_trial_20261108'
trial.AUTH = ('Operator designated the current teaching as final, returned the plate '
              'to pickup holder and empty arm near Home, and requested full calibration '
              'then transfer to this exact new destination. Claws remain closed; '
              'no release, return, imaging or automatic retry.')

if __name__ == '__main__':
    trial.prepare()
    if '--execute' in sys.argv:
        trial.calibration.OUT = trial.OUT
        trial.calibration.AUTH = trial.AUTH
        trial.calibration.main(calibration_only=True)
        result = json.loads((trial.OUT / 'run.json').read_bytes())
        if result['status'] != 'full_calibration_loaded_home_completed_pending_operator_assessment':
            raise RuntimeError('Fresh calibration did not complete')
        trial.travel.PLAN = trial.PLAN
        trial.travel.SHA = trial.sha(trial.PLAN)
        trial.travel.OUTPUT = trial.OUT / 'new_destination_transfer.json'
        trial.travel.main(expected_speeds=(137,137,137,5), vertical_legs=(0,3))
