"""Fresh operator-requested retry; unchanged calibration and pickup to Home."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_for_hamilton_retry02_20261108'
workflow.AUTH = ('Operator explicitly requested retry after the stationary vision '
                 'rejection. Plate remains in pickup holder and claws empty; '
                 'Hamilton parked/idle, access open, destination empty, route '
                 'clear and E-stop supervised were confirmed. Run unchanged '
                 'calibration, alignment, descent, grip, proof lift and loaded '
                 'Home. Hamilton travel is a separately checked continuation; '
                 'no automatic retry or fault clearing.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
