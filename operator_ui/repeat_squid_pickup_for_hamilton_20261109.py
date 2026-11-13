"""Second pickup to Home within the operator-authorized handling repeat."""
import pickup_squid_home_20261103 as pickup
from repeat_squid_dropoff_for_hamilton_20261109 import AUTH
from squid_handling_route import CURRENT_SOURCE, CURRENT_SHA

OUT=pickup.FOLDER/'repeat_squid_hamilton_20261109/pickup'

if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    pickup.main(OUT,AUTH,route_source=CURRENT_SOURCE,route_sha=CURRENT_SHA)
