"""One-shot native cleanup preparation for the current recorded calibration."""
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep
root=Path(__file__).resolve().parents[1] / 'hamilton_api'
log=root / 'polling_20261025T080235Z_4e315de3/cleanup_begin.jsonl'
assert not log.exists(), 'Never replay a native write.'
with urlopen('http://127.0.0.1:5002/researcher/api/lacry/state') as response:state=json.load(response)
op=state['links']['hamilton']['operation']
assert state['running']['active'] and op['request_id']=='731faefc2a214375916c3a4825f47c00' and op['status']=='running'
rows=[json.loads(x) for x in (root/(op['request_id']+'.jsonl')).read_text().splitlines()]
events=[json.loads(x['data']['event']['data']) for x in rows if x['kind']=='event' and isinstance(x['data'].get('event'),dict) and x['data']['event'].get('code')=='generic']
assert any(x.get('Name')=='ShowDialog' and x.get('Source')=='Unloads' and x.get('Payload')=='05244e3876be49f99b65f2a816f8e3b0' for x in events)
def record(kind,data):
    with log.open('a',encoding='utf-8') as out:out.write(json.dumps(dict(at=time.time(),kind=kind,data=data))+'\n')
h=HamiltonPrep()
record('request',dict(method='POST',path='calibration/begin-cleanup',body=None))
try:
    result=h.call('POST','calibration/begin-cleanup');record('response',result);print('begin-cleanup accepted',result)
except Exception as error:record('error',str(error));raise
