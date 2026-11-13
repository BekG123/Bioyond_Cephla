"""Record operator-confirmed HOME custody for one failed pre-pickup handoff."""
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen
import psutil

root=Path(__file__).resolve().parents[1];folder=root/'runs/composed_transfers'
ident='ba6531e1f21b4086ad75fdad3d57e8b7'
hold=folder/'unresolved.json';raw=hold.read_bytes();marker=json.loads(raw)
path=folder/(ident+'.json');run_raw=path.read_bytes();record=json.loads(run_raw)
if marker.get('run_id')!=ident or Path(marker['record']).resolve()!=path.resolve():raise RuntimeError('Hold changed.')
if psutil.pid_exists(marker['pid']):raise RuntimeError('Recorded owner still exists; no reconciliation.')
with urlopen('http://127.0.0.1:5002/state',timeout=10) as response:state=json.load(response)
if state['sequence']['active']:raise RuntimeError('Console sequence active.')
if (record['status']!='stopped_or_uncertain' or record['error']!='Start at original holder orientation.'
        or record['steps'][0]['step']!='retrieve_hotel' or record['steps'][0]['status']!='completed'
        or record['steps'][1]['step']!='register_barcode' or len(record['steps'])!=2
        or record.get('stop_response',{}).get('ok') is not True):raise RuntimeError('Failure evidence changed.')
retrieval=Path(record['steps'][0]['result']['record']);retrieval_raw=retrieval.read_bytes()
receipt=json.loads(retrieval_raw)
registration=folder/'handoffs'/retrieval.stem/'registration.json'
registration_raw=registration.read_bytes();reg=json.loads(registration_raw)
if (receipt['status']!='completed_retrieval_HOME_released_operator_observation_pending'
        or reg['status']!='blocked_or_uncertain' or len(reg['sides'])!=1
        or reg['sides'][0]['status']!='presenting' or reg['sides'][0]['scans']
        or reg['sides'][0].get('pickup')):raise RuntimeError('Registration progressed; inspect it.')
resolution=dict(status='resolved_operator_confirmed_HOME',at=time.time(),
    operator_statement='Yes—plate flat in HOME; jaws empty and clear',
    plate_location='HOME',plate_id=None,identity_status='unregistered_pending_fresh_scan',
    source_record=str(path),source_sha256=hashlib.sha256(run_raw).hexdigest(),
    retrieval_sha256=hashlib.sha256(retrieval_raw).hexdigest(),
    registration_sha256=hashlib.sha256(registration_raw).hexdigest(),
    reason='Live original-angle gate rejected before barcode pickup; no scan dispatched.',
    original_run_preserved=True,physical_commands_sent=False,automatic_retry=False,
    requires_fresh_plan_and_human_confirmation=True,
    next_start='Plate is HOME. A new slot-1 command requires operator reseating in slot 1.')
archive=folder/(ident+'.hold-cleared.json')
if archive.exists() or hold.read_bytes()!=raw or path.read_bytes()!=run_raw:raise RuntimeError('Evidence changed.')
with (folder/(ident+'.resolution.json')).open('x',encoding='utf-8') as stream:json.dump(resolution,stream,indent=2)
if hold.read_bytes()!=raw:raise RuntimeError('Hold changed; marker retained.')
hold.rename(archive)
print(json.dumps(dict(resolved=True,motion_started=False,resolution=str(folder/(ident+'.resolution.json')))))
