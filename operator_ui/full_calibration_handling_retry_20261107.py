"""Explicitly requested fresh calibration and one handling cycle."""
import full_calibration_handling_20261103 as workflow
from full_calibration_ten_handling_20261103 import stage_ready

workflow.OUT = workflow.FOLDER/'full_calibration_handling_retry_20261107'
workflow.AUTH = ('Operator returned plate to pickup holder after separate release '
                 'and empty return Home, and requested fresh full calibration plus '
                 'one Squid drop-off/pickup cycle. Unchanged accepted setup and '
                 'clearance; no imaging, repeated batch, automatic retry or restart.')

if __name__ == '__main__':
    stage_ready()
    workflow.main()
