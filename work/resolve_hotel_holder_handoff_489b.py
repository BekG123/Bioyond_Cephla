"""Reconcile one stopped run using the operator's HOME observation; no hardware."""
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen
import psutil

root=Path(__file__).resolve().parents[1]
folder=root/'runs/composed_transfers'
ident='489bb955bbe9404ca35d833e21d6ba19'
hold=folder/'unresolved.json';raw=hold.read_bytes();marker=json.loads(raw)
path=folder/(ident+'.json');run_raw=path.read_bytes();record=json.loads(run_raw)
if marker.get('run_id')!=ident or Path(marker['record']).resolve()!=path.resolve():
    raise RuntimeError('Unresolved run changed; no reconciliation.')
if psutil.pid_exists(marker['pid']):raise RuntimeError('Recorded owner PID exists; inspect before reconciliation.')
with urlopen('http://127.0.0.1:5002/state',timeout=10) as response:state=json.load(response)
if state['sequence']['active']:raise RuntimeError('Console sequence active; no reconciliation.')
if (record['status']!='stopped_or_uncertain' or record['error']!='Hotel release/holder feedback mismatch.'
        or record['steps'][0]['step']!='retrieve_hotel' or record['steps'][0]['status']!='completed'
        or record['steps'][1]['step']!='register_barcode' or record['steps'][1]['status']!='dispatching'
        or len(record['steps'])!=2 or record.get('stop_response',{}).get('ok') is not True):
    raise RuntimeError('Failure evidence changed; no reconciliation.')
retrieval=Path(record['steps'][0]['result']['record']);retrieval_raw=retrieval.read_bytes()
receipt=json.loads(retrieval_raw)
if receipt['status']!='completed_retrieval_HOME_released_operator_observation_pending':
    raise RuntimeError('Retrieval not completed.')
resolution=dict(status='resolved_operator_confirmed_HOME',at=time.time(),
    operator_statement='Flat in HOME; jaws empty and clear',plate_location='HOME',
    plate_id=None,identity_status='unregistered_pending_fresh_scan',
    source_record=str(path),source_sha256=hashlib.sha256(run_raw).hexdigest(),
    retrieval=str(retrieval),retrieval_sha256=hashlib.sha256(retrieval_raw).hexdigest(),
    cause='Released holder E2=1.7383376785598994 below 1.740; registration handoff rejected before scanner dispatch.',
    original_run_preserved=True,physical_commands_sent=False,automatic_retry=False,
    requires_fresh_plan_and_human_confirmation=True,
    next_start='Plate is HOME, not slot 1; do not repeat rack retrieval without reseating it in the rack.')
if hold.read_bytes()!=raw or path.read_bytes()!=run_raw:raise RuntimeError('Evidence changed.')
archive=folder/(ident+'.hold-cleared.json')
if archive.exists():raise RuntimeError('Hold archive already exists.')
with (folder/(ident+'.resolution.json')).open('x',encoding='utf-8') as stream:json.dump(resolution,stream,indent=2)
if hold.read_bytes()!=raw:raise RuntimeError('Hold changed; resolution written but marker retained.')
hold.rename(archive)
print(json.dumps(dict(resolved=True,resolution=str(folder/(ident+'.resolution.json')),motion_started=False)))
