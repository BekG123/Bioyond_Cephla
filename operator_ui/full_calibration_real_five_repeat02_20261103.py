"""Second explicitly requested full calibration / real-camera imaging run."""
import full_calibration_real_five_20261103 as workflow

workflow.OUT = workflow.imaging.ROOT/'reports/squid_48well_approach/full_calibration_real_five_repeat02_20261103'
workflow.AUTH = ('Operator accepted the preceding full-calibration, drop-off, five real images, '
                 'pickup/Home run without manual correction and requested the same sequence again. '
                 'Plate returned to arm pickup holder; claws empty; existing clearance and '
                 'on-site supervision authorization retained. Unchanged paths and settings.')

if __name__ == '__main__':
    workflow.main()
