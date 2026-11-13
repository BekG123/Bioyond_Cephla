"""Release the current operator-confirmed seated plate and return empty Home."""
import json
import time
import release_empty_home_20261103 as release
from proof_lift_plate import api, write
from squid_handling_route import CURRENT_SOURCE, CURRENT_SHA

FOLDER = release.FOLDER / 'squid_forward_after_calibration_20261109'
AUTH = ('Operator confirmed the plate is level and correctly seated at Squid '
        'after this forward run, then requested release and Home. Existing '
        'clear-route and E-stop supervision confirmation applies. Open to 7 mm '
        'at speed 5; continuous vertical retreat at 5, then empty Home at 137. '
        'No imaging, pickup, startup, fault clearing or automatic retry.')

if __name__ == '__main__':
    state = api('state')
    if not state['robot'].get('connected'):
        assert not state['sequence']['active']
        assert api('connect', {'ip':'192.168.201.220'})['ok']
    assert api('researcher/api/status')['hand_guiding']['state'] == 'off'
    assert not api('researcher/api/lacry/state')['running']['active']
    accepted = FOLDER/'seating_operator_acceptance.json'
    if not accepted.exists():
        write(accepted, dict(at=time.time(), operator_response='Ye. Now release and go home',
              observation='Plate level and correctly seated in Squid holder',
              forward_receipt_sha256=release.sha(FOLDER/'transfer.json'), authorization=AUTH))
    release.main(FOLDER, AUTH, route_source=CURRENT_SOURCE, route_sha=CURRENT_SHA,
                 completed_forward_receipt=FOLDER/'transfer.json',
                 completed_forward_plan=FOLDER/'plan.json')
