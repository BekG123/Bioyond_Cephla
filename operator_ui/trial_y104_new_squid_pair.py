"""Requested +Y10.4 pickup trial; preserve the current Squid destination.

The operator rejected the physical seating after the +Y11.4 transfer.
Plate returned to pickup holder, claws confirmed empty. Requires a fresh
successful calibration; stops open at descent for inspection, never grips.
"""
from trial_pickup_inward64 import main

if __name__ == '__main__':
    main(direction='positive_base_y', total_shift=10.4,
         parent_sha='e9a4383f10007cb72dba147fb29d05dde67323a4b9586cb3089bb207064c45e9')
