"""Operator-requested usual full calibration, unchanged steps, fresh records."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'full_calibration_retry03_20261109'
workflow.AUTH = ('Operator explicitly requested the usual full calibration again '
                 'with its existing automatic E2 correction. Existing confirmed '
                 'empty jaws, plate in calibration holder, clear pickup/Home route '
                 'and supervised E-stop apply. Run calibration, alignment, descent, '
                 'grip, proof lift and loaded Home using existing routines. '
                 'No automatic retry or changes to geometry or checks.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
