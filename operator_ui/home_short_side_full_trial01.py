"""Confirmed empty Home return before the short-side pickup/transfer trial."""
import json
import time
import argparse
from proof_lift_plate import api,near
from draggo import DragGoRPC
from hamilton_short_side_trial import FOLDER,reference

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision',choices=('01','02','03'),default='01')
parser.add_argument('--startup-refusal-retry',action='store_true')
args=parser.parse_args();revision=args.revision
p,parent=reference();path=FOLDER/('full_sequence'+revision+'_initial_home.json')
if args.startup_refusal_retry:
    assert revision=='03'
    old=json.loads(path.read_bytes())
    refusal=old['samples'][-1]['sequence']['result']['home_startup_refusal']
    assert refusal['home_travel_dispatched'] is False and refusal['program_start_sent'] is False
    assert json.loads((FOLDER/'full_sequence03_empty_start.json').read_bytes())['status']=='completed'
    path=FOLDER/'full_sequence03_initial_home_retry01.json'
if path.exists():raise RuntimeError('Initial Home already attempted; inspect record')
s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:assert api('connect',{'ip':'192.168.201.220'})['ok']
def check(allow_preparation=False):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    assert r['ok'] and r['connected'] and not r['errors']
    if not allow_preparation:assert r['enabled'] and r['program_state']['state']=='running'
    assert not any(n[k] for k in ('manual','error','emergency','drag')) and abs(n['external_axes']['E1'])<.15
    return s,n
s,n=check(allow_preparation=revision=='03');assert not s['sequence']['active'] and not n['moving']
expected_start=dict(X=312.917,Y=-43.419,Z=117.933,Rz=-56.166) if revision=='02' else dict(X=318.655,Y=-73.428,Z=134.101,Rz=4.431)
if revision=='03':expected_start=dict(X=254.554,Y=-30.284,Z=128.065,Rz=21.217)
near(s['robot']['pose_mm'],expected_start,.1)
proposal=api('researcher/api/lacry/button/move_home',{})
assert proposal.get('ok'),proposal
plan=proposal['plan'];assert plan['dispatch']=='ik_home_return'
near(plan['start'],s['robot']['pose_mm'],.05);near(plan['home'],parent['home'],.01)
record=dict(status='started',at=time.time(),plan=plan,samples=[],authorization='Operator confirmed empty jaws, new Home route, pickup and revised Hamilton route clear; hands clear; E-stop supervised.')
with path.open('x') as f:json.dump(record,f,indent=2)
def save():path.write_text(json.dumps(record,indent=2))
try:
    record['response']=api('researcher/api/lacry/confirm',dict(ready=True,plan_id=plan['id']));save()
    assert record['response'].get('ok'),record['response']
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        s,n=check(allow_preparation=revision=='03');seq=api('seq');record['samples'].append(dict(at=time.time(),state=s,native=n,sequence=seq));save()
        if not seq['active']:
            assert seq['state']=='done' and seq['result'].get('ok'),seq
            check()
            near(s['robot']['pose_mm'],parent['home'],.1);assert not n['moving']
            record.update(status='completed',final_state=s);break
        time.sleep(.2)
    else:raise RuntimeError('Home timed out')
except Exception as e:
    record.update(status='failed_or_uncertain',error=str(e))
    if api('seq')['active']:record['stop_response']=api('researcher/api/lacry/stop',{})
    raise
finally:record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],report=str(path))))
