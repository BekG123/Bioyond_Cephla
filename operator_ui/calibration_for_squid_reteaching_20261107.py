"""Calibrate and pick up to Home; no Squid movement after fixture relocation."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_for_squid_reteaching_20261107'
workflow.AUTH = ('Operator moved the microscope and will manually teach its new '
                 'plate seating position. Plate confirmed in arm pickup holder, '
                 'claws empty and Home route clear. Full calibration, pickup and '
                 'loaded Home only. No Squid movement, release, imaging or retry.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
