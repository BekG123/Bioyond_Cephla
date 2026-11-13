"""Requested repeat: fresh calibration and one Squid handling cycle."""
import full_calibration_handling_20261103 as workflow
from full_calibration_ten_handling_20261103 import stage_ready

workflow.OUT = workflow.FOLDER / 'full_calibration_handling_retry02_20261107'
workflow.AUTH = ('Operator returned the plate to the arm pickup holder and requested '
                 'another full calibration and one Squid drop-off/pickup cycle. '
                 'Unchanged accepted setup and clearance; empty claws. No imaging, '
                 'automatic retry, controller restart, or repeated batch.')

if __name__ == '__main__':
    stage_ready()
    workflow.main()
