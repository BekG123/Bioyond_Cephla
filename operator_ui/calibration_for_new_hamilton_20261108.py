"""Fresh calibration/pickup to Home before the requested new Hamilton trial."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_for_new_hamilton_20261108'
workflow.AUTH = ('Operator returned the empty arm and plate to the pickup holder '
                 'and requested full calibration then the new saved Hamilton path. '
                 'Use unchanged 48-well pickup and loaded Home. Stop on failure; '
                 'Hamilton trial is separately checked, with no plate release.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
