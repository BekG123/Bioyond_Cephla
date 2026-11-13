"""Operator-requested +Y 9.4 mm total pickup trial, stopping open for inspection."""
from trial_pickup_inward64 import main

if __name__ == '__main__':
    main(direction='positive_base_y', total_shift=9.4,
         parent_sha='b687fa2cf3747acebfd3da8a56a2e4d330e9d074bb907b8877072e35db8d04da')
