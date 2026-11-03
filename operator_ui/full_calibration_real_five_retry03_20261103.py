"""Explicit operator-requested retry after stationary vision rejection."""
import full_calibration_real_five_20261103 as workflow

workflow.OUT = workflow.imaging.ROOT/'reports/squid_48well_approach/full_calibration_real_five_retry03_20261103'
workflow.AUTH = ('Operator explicitly requested a retry after repeat02 stopped on stationary '
                 'vision disagreement. Plate remains in pickup holder, claws empty; existing '
                 'clearance and supervision retained. Full calibration, drop-off, five real '
                 'images, pickup/Home with unchanged checks and no automatic retry.')

if __name__ == '__main__':
    workflow.main()
