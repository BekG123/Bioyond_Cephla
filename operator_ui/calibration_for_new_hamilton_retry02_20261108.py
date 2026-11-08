"""Operator-requested retry after E2 settled and manual program startup."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_for_new_hamilton_retry02_20261108'
workflow.AUTH = ('Operator requested retry of full 48-well calibration and the new '
                 'Hamilton path, then confirmed controller startup. Plate remains '
                 'in pickup holder, claws empty, route clear under existing '
                 'supervision. Unchanged calibration, pickup and loaded Home; '
                 'new Hamilton trial checked separately. No automatic retry, '
                 'fault clearing or plate release.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
