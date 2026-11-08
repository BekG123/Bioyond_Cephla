"""Fresh calibration receipt for the requested Hamilton drop-off repeat."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_hamilton_dropoff_repeat01_20261108'
workflow.AUTH = ('Operator requested full 48-well calibration, pickup, loaded '
                 'Hamilton transfer, release and empty Home. Plate is in the arm '
                 'holder; arm empty at Home. Operator confirmed the earlier '
                 'Hamilton plate was freed and channels/deck clear; native '
                 'recovery completed with parked feedback. This wrapper runs '
                 'calibration through loaded Home only; Hamilton is checked '
                 'separately. Preserve existing guards; no automatic retry.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
