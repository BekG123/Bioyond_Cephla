"""Fresh operator-requested full calibration and pickup to Home."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_repeat02_20261108'
workflow.AUTH = ('Operator requested full calibration again and confirmed plate '
                 'back in pickup holder, claws empty and route clear. One fresh '
                 'calibration, alignment, descent, grip, proof lift and loaded Home. '
                 'No Squid movement, release, imaging or automatic retry.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
