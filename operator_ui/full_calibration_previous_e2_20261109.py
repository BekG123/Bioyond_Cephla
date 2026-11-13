"""User-requested full calibration with restored previous E2 acceptance."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'full_calibration_previous_e2_20261109'
workflow.AUTH = ('Operator requested previous successful full calibration code, '
                 'without the stricter E2 minimum. Standing confirmed empty jaws, '
                 'plate flat in calibration holder, clear route, released arm, '
                 'hands clear and supervised E-stop apply. Existing calibration, '
                 'alignment, descent, grip, proof lift and loaded Home only.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
