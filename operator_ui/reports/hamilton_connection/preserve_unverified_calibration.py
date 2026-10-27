"""Preserve native-finished evidence before replacing the stale host monitor.

No hardware writes. Does not clear the active marker or assert calibration Pass.
"""
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep
root=Path(__file__).resolve().parents[1]/'hamilton_api'
folder=root/'polling_20261025T080235Z_4e315de3'
with urlopen('http://127.0.0.1:5002/researcher/api/lacry/state') as response:state=json.load(response)
op=state['links']['hamilton']['operation']
assert op['request_id']=='731faefc2a214375916c3a4825f47c00'
journal=root/(op['request_id']+'.jsonl')
rows=[json.loads(x) for x in journal.read_text().splitlines()]
assert any(x['kind']=='event' and isinstance(x['data'].get('event'),dict) and x['data']['event'].get('code')=='finished' for x in rows)
h=HamiltonPrep()
snapshot={p:h.call('GET',p) for p in ('instruments/global-run-state','protocol-run',
    'service-software-api/is-parked','service-software-api/has-tips','errors/check-for-pending-errors','calibration/channel-results')}
assert snapshot['instruments/global-run-state']=='Idle'
assert not snapshot['protocol-run']['isRunInProgress']
assert snapshot['service-software-api/is-parked'] is True and snapshot['service-software-api/has-tips'] is False
assert not snapshot['errors/check-for-pending-errors']
requests=[json.loads(x) for x in (folder/'requests.jsonl').read_text().splitlines()]
initial=next(x['data']['id'] for x in requests if x['kind']=='request' and x['data']['path']=='calibration/channel-results')
before=next(x['data']['result'] for x in requests if x['kind']=='response' and x['data']['id']==initial)
assert {x['id'] for x in snapshot['calibration/channel-results']}=={x['id'] for x in before}
op.update(status='finished_unverified',native_finished=True,
    error='Native finished and Idle, but no new channel result was published. Host monitor stopped by guarded reload without another abort; marker retained for review.')
record=dict(at=time.time(),status='finished_unverified',operation=op,native=snapshot,
    controller_writes_sent_by_this_script=0,marker_retained=True,
    evidence='Native finished event, Idle, parked, no attached tips, no pending errors, unchanged channel-result IDs.',
    operator_observation='Old tool-not-detected popup remained; no new Finish screen visible.')
(folder/'finished_unverified_review.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
(root/'active.json').write_text(json.dumps(op,indent=2),encoding='utf-8')
with journal.open('a',encoding='utf-8') as out:out.write(json.dumps(dict(at=time.time(),kind='manual_terminal_review',data=record))+'\n')
print(json.dumps({k:v for k,v in record.items() if k not in ('native','operation')}))
