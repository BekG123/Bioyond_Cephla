"""Accepted Squid pickup and loaded Home, first half of requested transfer."""
import time
import pickup_squid_home_20261103 as pickup
from proof_lift_plate import write
from squid_handling_route import CURRENT_SOURCE, CURRENT_SHA

OUT = pickup.FOLDER/'pickup_squid_for_hamilton_20261109'
AUTH = ('Operator confirmed plate remained seated after Squid release and requested '
        'transfer to Hamilton via Home. Accepted Squid route and two-speed (approach10, final1mm at5) grip to '
        '3.9 mm; loaded return Home. Route clear and E-stop supervision established. '
        'Hamilton door open, holder empty/unchanged and approach clear confirmed. '
        'Hamilton travel checked separately. No retries, reset or release.')

if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    receipt = OUT/'authorization.json'
    if not receipt.exists():
        write(receipt, dict(at=time.time(), authorization=AUTH,
              previous_release=str(pickup.FOLDER/'squid_forward_after_calibration_20261109/release_empty_home_20261103.json'),
              operator_observation='Plate stayed seated in Squid after empty retreat'))
    pickup.main(OUT, AUTH, route_source=CURRENT_SOURCE, route_sha=CURRENT_SHA)
