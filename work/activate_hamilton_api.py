"""Operator-approved discard of one blocked preview, then disconnected reload."""
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
def read(path):
    with urlopen('http://127.0.0.1:5002/'+path,timeout=10) as response:return json.load(response)

state=read('state');chat=read('researcher/api/lacry/state')
if state['sequence']['active'] or chat.get('busy') or chat.get('running',{}).get('active') or chat.get('review'):
    raise RuntimeError('Console is no longer disconnected and idle; no changes sent.')
if state['robot']['connected']:
    if '--disconnect-approved' not in sys.argv:raise RuntimeError('Robot connected; disconnect approval required.')
    time.sleep(.5)
    fresh=read('state')
    if fresh['sequence']['active'] or not fresh['robot'].get('ok') or any(
            abs(fresh['robot']['pose_mm'][k]-state['robot']['pose_mm'][k])>.02 for k in ('X','Y','Z','Rz')):
        raise RuntimeError('Arm is changing state; no disconnect sent.')
    folder=ROOT/'operator_ui/reports/deployments'/('hamilton_api_disconnect_'+str(time.time_ns()))
    folder.mkdir(parents=True)
    (folder/'before.json').write_text(json.dumps({'state':state,'chat':chat},indent=2),encoding='utf-8')
    request=Request('http://127.0.0.1:5002/disconnect',data=b'{}',headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=10) as response:result=json.load(response)
    if result.get('ok') is not True or read('state')['robot']['connected']:
        raise RuntimeError('Disconnect unverified; no reload.')
pending=chat.get('pending')
if pending:
    if pending.get('id') not in ('0adb7d8cf0744ef5ac6de621b4cdc074','748d02245fea427c9f13c58f5804d1e3') or pending.get('executable') is not False:
        raise RuntimeError('The pending decision changed; no cancellation sent.')
    folder=ROOT/'operator_ui/reports/deployments'/('hamilton_api_'+str(time.time_ns()))
    folder.mkdir(parents=True)
    (folder/'discarded_preview.json').write_text(json.dumps(pending,indent=2),encoding='utf-8')
    request=Request('http://127.0.0.1:5002/researcher/api/lacry/cancel',
        data=json.dumps({'plan_id':pending['id']}).encode(),headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=10) as response:result=json.load(response)
    if result.get('ok') is not True:raise RuntimeError('Preview cancellation did not complete. No reload.')
subprocess.run([sys.executable,'-B',str(ROOT/'work/reload_lacry_reply_fix.py')],cwd=ROOT,check=True)
catalog=read('researcher/api/lacry/hamilton/api-catalog')
print(json.dumps({'catalog_operations':catalog['total_operations'],'schema_hash':catalog['schema_hash']}))
for path in ('static/hamilton_api.js?v=20261112','static/supervised_experiment.js?v=20261112-hamilton-api'):
    with urlopen('http://127.0.0.1:5002/'+path,timeout=10) as response:
        if response.status!=200:raise RuntimeError('Missing browser asset: '+path)
print('New API catalog and browser assets available. No hardware connected or started.')
