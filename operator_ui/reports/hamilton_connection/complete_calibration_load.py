"""Complete the recorded site-7 loading handshake once, after native preparation."""
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep

root = Path(__file__).resolve().parents[1] / 'hamilton_api'
log = root / 'polling_20261025T080235Z_4e315de3/loading_complete.jsonl'
assert not log.exists(), 'Do not replay this acknowledgement.'
with urlopen('http://127.0.0.1:5002/researcher/api/lacry/state') as response:
    state = json.load(response)
op = state['links']['hamilton']['operation']
assert state['running']['active'] and op['request_id'] == '731faefc2a214375916c3a4825f47c00'
assert op['status'] == 'running' and op['step'] == 'channel_calibration'
assert op['calibration_setup']['tip_site'] == 7 and op['calibration_setup']['tip_labware_id'] == 273
assert 'PrepareLoadingFinished' in (root / (op['request_id'] + '.jsonl')).read_text()
h = HamiltonPrep()
def record(kind, data):
    with log.open('a', encoding='utf-8') as out:
        out.write(json.dumps(dict(at=time.time(), kind=kind, data=data)) + '\n')
for path in ('service-software-api/sensor-status', 'errors/check-for-pending-errors'):
    result = h.call('GET', path)
    record('read', dict(path=path, result=result))
    if path.endswith('sensor-status'):
        assert result['isDoorClosed'] and result['isEnclosurePresent']
    else:
        assert not result
record('request', dict(method='POST', path='calibration/end-load', body=None,
    authority='User confirmed full rack at site 7, lid removed, door closed and hands clear.'))
try:
    result = h.call('POST', 'calibration/end-load')
    record('response', result)
    print('end-load accepted:', result)
except Exception as error:
    record('error', str(error))
    raise
