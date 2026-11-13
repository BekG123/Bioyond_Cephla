"""One requested repeat drop-off and empty Home, using accepted routines."""
import json
import sys
import time
import dropoff_approach_20261103 as approach
import release_empty_home_20261103 as release
from proof_lift_plate import api, write
from squid_handling_route import CURRENT_SOURCE, CURRENT_SHA

OUT = approach.FOLDER/'repeat_squid_hamilton_20261109'
AUTH = ('Operator confirmed successful arrival at Hamilton, then explicitly '
        'requested Hamilton -> Home -> Squid, release, empty Home, Squid pickup '
        'and delivery to Hamilton again. Existing unchanged fixtures, clear '
        'routes and E-stop supervision apply. Repeat accepted handling without '
        'routine waypoint confirmation; stop on fault or uncertain completion.')

if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    approach.main(OUT, route_source=CURRENT_SOURCE, route_sha=CURRENT_SHA)
    if '--execute' in sys.argv:
        receipt = json.loads((OUT/'dropoff_approach_trial_20261103.json').read_bytes())
        assert receipt['status']=='at_squid_awaiting_supported_plate_confirmation'
        write(OUT/'repeat_authorization.json',dict(at=time.time(),authorization=AUTH,
            physical_observation='Operator accepted prior Squid seating and release; unchanged setup repeated',
            new_visual_observation=False))
        release.main(OUT, AUTH, route_source=CURRENT_SOURCE, route_sha=CURRENT_SHA)
