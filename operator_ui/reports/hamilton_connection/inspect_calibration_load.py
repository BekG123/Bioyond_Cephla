"""One-shot, recorded loading handshake for the owned site-7 calibration trial."""
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep

folder = Path(__file__).resolve().parents[1] / 'hamilton_api/polling_20261025T080235Z_4e315de3'
log = folder / 'loading_handshake.jsonl'

def record(kind, data):
    with log.open('a', encoding='utf-8') as out:
        out.write(json.dumps(dict(at=time.time(), kind=kind, data=data)) + '\n')

with urlopen('http://127.0.0.1:5002/researcher/api/lacry/state') as response:
    state = json.load(response)
operation = state['links']['hamilton']['operation']
assert state['running']['active'] and operation['request_id'] == '731faefc2a214375916c3a4825f47c00'
assert operation['status'] == 'running' and operation['step'] == 'channel_calibration'
assert operation['calibration_setup']['tip_site'] == 7
assert not log.exists(), 'Do not replay the loading handshake.'
h = HamiltonPrep()
for path in ('instruments/global-run-state', 'service-software-api/sensor-status', 'errors/check-for-pending-errors'):
    result = h.call('GET', path)
    record('read', dict(path=path, result=result))
    if path.endswith('global-run-state'):
        assert result == 'CalibrationAssayRunning'
    elif path.endswith('sensor-status'):
        assert result['isDoorClosed'] and result['isEnclosurePresent']
    else:
        assert not result
record('request', dict(method='POST', path='calibration/begin-load', body=None))
try:
    result = h.call('POST', 'calibration/begin-load')
    record('response', result)
    print('begin-load:', result)
    for path in ('protocol-run', 'protocol-run/load-instructions'):
        result = h.call('GET', path)
        record('read', dict(path=path, result=result))
        print(path, json.dumps(result))
except Exception as error:
    record('error', str(error))
    raise
