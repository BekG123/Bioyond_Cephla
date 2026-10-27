"""Archive a verified-terminated ownership marker for the user's requested new calibration.

Preserves the unverified outcome; never creates a Pass or writes to Hamilton.
"""
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep
root=Path(__file__).resolve().parents[1]/'hamilton_api'
marker=root/'active.json'
previous=json.loads(marker.read_text())
assert previous['request_id']=='731faefc2a214375916c3a4825f47c00'
assert previous['status']=='finished_unverified' and previous['native_finished'] is True
with urlopen('http://127.0.0.1:5002/researcher/api/lacry/state') as response:state=json.load(response)
assert not state['busy'] and not state['running']['active'] and not state['pending']
h=HamiltonPrep()
current={p:h.call('GET',p) for p in ('instruments/global-run-state','protocol-run',
    'service-software-api/is-parked','service-software-api/has-tips','errors/check-for-pending-errors')}
assert current['instruments/global-run-state']=='Idle' and not current['protocol-run']['isRunInProgress']
assert current['service-software-api/is-parked'] is True and current['service-software-api/has-tips'] is False
assert not current['errors/check-for-pending-errors']
folder=root/'polling_20261025T080235Z_4e315de3'
destination=folder/'reviewed_before_ui_retry_active.json'
assert not destination.exists()
record=dict(at=time.time(),prior_outcome='finished_unverified',native=current,controller_writes=0,
    authority='User explicitly requested a new calibration from Lacry browser UI with sequence and handshake recording.',
    decision='Prior operation is verified terminated. Archive its ownership marker to allow the requested new calibration; do not certify its missing result.')
(folder/'review_for_authorized_retry.json').write_text(json.dumps(record,indent=2))
marker.rename(destination)
print(json.dumps(record))
