"""One freshly authorized calibration and Squid handling repeat."""
import full_calibration_handling_20261103 as workflow
from full_calibration_ten_handling_20261103 import stage_ready

workflow.OUT = workflow.FOLDER / 'full_calibration_handling_retry06_20261107'
workflow.AUTH = ('Operator requested a repeat and confirmed the plate is back in '
                 'the arm pickup holder, claws empty and route clear. One full '
                 'calibration and Squid drop-off/pickup, ending loaded at Home. '
                 'Unchanged setup, speeds and checks; no imaging or automatic retry.')

if __name__ == '__main__':
    stage_ready()
    workflow.main()
