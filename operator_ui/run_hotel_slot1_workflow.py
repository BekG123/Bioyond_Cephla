"""Accepted 48-well HOME/slot1 handling; preview by default.

--execute confirms the requested setup: empty jaws at HOME clearance, plate
flat in HOME for delivery or slot1 for retrieval, destination empty, unchanged
rack, clear loaded route/opening/5mm lift, hands clear and E-stop supervised.
Does not start Lua, clear faults, enable hand-guiding, calibrate or retry.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4
from run_cellvis24_scanner_hamilton import api,reconnect,dispatch
from run_record_io import write_run_record
from scope_step_trial import near

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/'Pick and Hold/Station Handling/workflows/hotel_slot1_v1.json'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def load_workflow():
    from hotel_slot1_delivery import geometry as delivery
    from hotel_slot1_retrieval import geometry as retrieval
    w=json.loads(WORKFLOW.read_bytes())
    if w['slot']!=1 or w['status']!='operator_accepted':raise RuntimeError('Accepted slot1 workflow required.')
    acceptance=ROOT/w['acceptance']
    if hashlib.sha256(acceptance.read_bytes()).hexdigest()!=w['acceptance_sha256']:
        raise RuntimeError('Acceptance evidence changed.')
    a=json.loads(acceptance.read_bytes())
    for rel,sha in a['artifact_sha256'].items():
        if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()!=sha:raise RuntimeError('Recorded trial evidence changed.')
    plans={'deliver':delivery(),'retrieve':retrieval()}
    if {k:digest(v) for k,v in plans.items()}!=w['geometry_sha256']:
        raise RuntimeError('Accepted slot1 geometry changed; review before running.')
    return w,plans

def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--action',choices=['deliver','retrieve','roundtrip'],default='roundtrip')
    p.add_argument('--execute',action='store_true',help='Execute the described setup; otherwise preview offline.')
    return p.parse_args(argv)

def run_phase(action,g):
    reconnect();s=api('state');r=s['robot']
    if s['sequence']['active'] or not r.get('enabled') or r.get('errors') or r.get('program_state',{}).get('state')!='running' or r.get('control_mode',{}).get('mode')!='auto':
        raise RuntimeError('Healthy running Auto and inactive sequencer required; no recovery.')
    near(r['pose_mm'],g['home'],.05)
    # Both actions start EMPTY at HOME clearance, above the seated plate.
    target=0 if action=='deliver' else 7
    actual=r.get('external_axes',{}).get('E1')
    if actual is None:raise RuntimeError('Fresh jaw feedback required.')
    if abs(actual-target)>.15:
        result=api('gripper',dict(action='move',e1=target,speed=5))
        if result.get('recovered'):raise RuntimeError('Uncertain jaw preparation; no retry.')
        near(api('state')['robot']['pose_mm'],g['home'],.05)
    endpoint='hotel-slot1-delivery' if action=='deliver' else 'hotel-slot1-retrieval'
    plan=api('developer/api/'+endpoint+'/preview',{})['plan']
    if plan['geometry']!=g:raise RuntimeError('Loaded backend differs from accepted workflow.')
    body=dict(plan=plan,estop_supervised=True)
    body.update(dict(plate_in_home=True,slot1_empty=True,loaded_route_clear=True) if action=='deliver'
                else dict(plate_in_slot1=True,home_empty=True,lift5_and_route_clear=True))
    return dispatch('developer/api/'+endpoint+'/start',body,endpoint.replace('-','_'),180)

def main(argv=None):
    args=parse_args(argv);w,plans=load_workflow()
    actions=['deliver','retrieve'] if args.action=='roundtrip' else [args.action]
    if not args.execute:
        print(json.dumps(dict(motion_started=False,workflow=w['id'],actions=actions,plans={k:plans[k] for k in actions}),indent=2))
        return
    folder=ROOT/'operator_ui/reports/plate_session/hotel_slot1_workflows';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(uuid4().hex+'.json');record=dict(at=time.time(),status='starting',actions=actions,steps=[],automatic_retries=False)
    def save():write_run_record(path,record)
    save()
    try:
        for action in actions:
            result=run_phase(action,plans[action]);record['steps'].append(dict(action=action,result=result));save()
        record['status']='completed_operator_observation_pending'
    except BaseException as e:
        record.update(status='stopped_or_uncertain',error=str(e));raise
    finally:
        record['finished_at']=time.time();save();print(json.dumps(dict(status=record['status'],record=str(path))),flush=True)

if __name__=='__main__':main()
