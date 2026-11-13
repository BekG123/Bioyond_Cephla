"""Fresh calibration-only attempt after camera recovery."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_for_squid_reteaching03_20261107'
workflow.AUTH = ('Operator requested retry after camera timeout and prepared the '
                 'controller. Plate in pickup holder, empty claws, clear route. '
                 'Full calibration and pickup to loaded Home for teaching the '
                 'closer microscope position. No Squid motion, release or retry.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
