"""Finish the current cleanup after the user's physical unloading confirmation."""
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep
root=Path(__file__).resolve().parents[1]/'hamilton_api'
log=root/'polling_20261025T080235Z_4e315de3/cleanup_complete.jsonl'
assert not log.exists(), 'Never replay a native write.'
with urlopen('http://127.0.0.1:5002/researcher/api/lacry/state') as response:state=json.load(response)
op=state['links']['hamilton']['operation']
assert state['running']['active'] and op['request_id']=='731faefc2a214375916c3a4825f47c00' and op['status']=='running'
assert 'UnloadStarted' in (root/(op['request_id']+'.jsonl')).read_text()
def record(kind,data):
    with log.open('a',encoding='utf-8') as out:out.write(json.dumps(dict(at=time.time(),kind=kind,data=data))+'\n')
h=HamiltonPrep()
sensors=h.call('GET','service-software-api/sensor-status');record('sensors',sensors)
assert sensors['isDoorClosed'] and sensors['isEnclosurePresent']
record('request',dict(method='POST',path='calibration/end-cleanup',body=None,
    authority='User confirmed rack removed; door closed; hands clear.'))
try:
    result=h.call('POST','calibration/end-cleanup');record('response',result);print('end-cleanup accepted',result)
except Exception as error:record('error',str(error));raise
