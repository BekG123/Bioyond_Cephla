"""Fresh full calibration and one handling cycle authorized by the operator."""
import full_calibration_handling_20261103 as workflow
from full_calibration_ten_handling_20261103 import stage_ready

workflow.OUT = workflow.FOLDER / 'full_calibration_handling_retry05_20261107'
workflow.AUTH = ('Operator attributed the prior grip interruption to their intervention '
                 'and requested another full sequence. Confirmed plate in pickup holder, '
                 'empty claws and clear route. Reviewed empty Home first. '
                 'One calibration and Squid drop-off/pickup only; no imaging, '
                 'automatic retry or changed tolerances.')

if __name__ == '__main__':
    stage_ready()
    workflow.main()
