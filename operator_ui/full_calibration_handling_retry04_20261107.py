"""Fresh operator-requested repeat after a vision verification rejection."""
import full_calibration_handling_20261103 as workflow
from full_calibration_ten_handling_20261103 import stage_ready

workflow.OUT = workflow.FOLDER / 'full_calibration_handling_retry04_20261107'
workflow.AUTH = ('Operator requested another attempt after alignment vision rejection. '
                 'Plate remains in pickup holder, claws empty, unchanged clear setup. '
                 'Reviewed empty Home then one full calibration and Squid drop-off/pickup. '
                 'No imaging, automatic retries, or changed tolerances.')

if __name__ == '__main__':
    stage_ready()
    workflow.main()
