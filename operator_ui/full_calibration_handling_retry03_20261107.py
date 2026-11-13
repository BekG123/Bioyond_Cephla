"""Operator-authorized retry with fresh calibration and handling receipts."""
import full_calibration_handling_20261103 as workflow
from full_calibration_ten_handling_20261103 import stage_ready

workflow.OUT = workflow.FOLDER / 'full_calibration_handling_retry03_20261107'
workflow.AUTH = ('Operator attributed the previous interruption to their intervention, '
                 'requested a fresh full calibration and one Squid drop-off/pickup, '
                 'and confirmed plate in pickup holder, empty claws and clear route. '
                 'Arm repositioned within workspace and returned Home using reviewed planner. '
                 'No imaging, automatic retries, or repeated batch.')

if __name__ == '__main__':
    stage_ready()
    workflow.main()
