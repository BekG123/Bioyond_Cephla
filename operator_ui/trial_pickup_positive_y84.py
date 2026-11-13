"""Additional +Y 2 mm from the accepted +Y 6.4 pickup; stop open."""
from trial_pickup_inward64 import main

if __name__=='__main__':
    main(direction='positive_base_y',total_shift=8.4,
         parent_sha='117ab05cfe1223abe32484277ab8a558429ca64acf9d4706bea97c49811923bc')
