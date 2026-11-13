"""Fresh pickup to Home for teaching the repositioned microscope."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_for_squid_reteaching02_20261107'
workflow.AUTH = ('Operator moved microscope closer to robot base and requested '
                 'full calibration and pickup to Home for manual teaching. Plate '
                 'in pickup holder, claws empty, clear Home route confirmed. '
                 'No Squid route, release, imaging, or automatic retry.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
