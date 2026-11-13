"""Proposed +Y 12.0 mm pickup trial; stops open for operator inspection."""
from trial_pickup_inward64 import main

if __name__ == '__main__':
    main(direction='positive_base_y', total_shift=12.0,
         parent_sha='746e1fd9de20bc51bd748caca47b2c6e21b88500b7d257645be356d4807d47a3')
