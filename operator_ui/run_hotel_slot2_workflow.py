"""Accepted 48-well HOME / slot2 workflow; offline preview by default.

--execute confirms empty jaws at HOME clearance, plate flat in HOME for deliver
or in slot2 for retrieve, destination empty, unchanged rack/plate profile, clear
opening and loaded route including 5mm lift, hands clear and E-stop supervised.
No calibration, startup, fault reset or automatic retry.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4
from run_cellvis24_scanner_hamilton import api,reconnect
from run_hotel_slot1_workflow import digest
from run_record_io import write_run_record
from scope_step_trial import near
from hotel_slot2_handling import geometry,OUTPUT

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/'Pick and Hold/Station Handling/workflows/hotel_slot2_v1.json'


def load_workflow():
    w=json.loads(WORKFLOW.read_bytes());g=geometry()
    if w['slot']!=2 or w['status']!='operator_accepted':raise RuntimeError('Accepted slot2 workflow required.')
    raw=(ROOT/w['acceptance']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=w['acceptance_sha256']:raise RuntimeError('Acceptance changed.')
    for file,sha in json.loads(raw)['artifact_sha256'].items():
        if hashlib.sha256((ROOT/file).read_bytes()).hexdigest()!=sha:raise RuntimeError('Trial evidence changed.')
    if digest(g)!=w['geometry_sha256']:raise RuntimeError('Accepted slot2 geometry changed.')
    return w,g


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action',choices=['deliver','retrieve','roundtrip'],default='roundtrip')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv);w,g=load_workflow()
    actions=['deliver','retrieve'] if args.action=='roundtrip' else [args.action]
    if not args.execute:
        print(json.dumps(dict(motion_started=False,workflow=w['id'],actions=actions,geometry=g),indent=2));return
    reconnect();s=api('state');r=s['robot']
    if (s['sequence']['active'] or not r.get('enabled') or r.get('errors') or
            r.get('program_state',{}).get('state')!='running' or r.get('control_mode',{}).get('mode')!='auto'):
        raise RuntimeError('Healthy running Auto required; no startup or recovery.')
    near(r['pose_mm'],g['home'],.05)
    from run_hotel_slot_trial import main as approach
    from run_hotel_slot2_handling import main as handling
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/('accepted_workflow_'+uuid4().hex+'.json')
    record=dict(at=time.time(),status='starting',workflow=w['id'],actions=actions,steps=[],automatic_retries=False)
    def save():write_run_record(path,record)
    def log(step,result):record['steps'].append(dict(step=step,result=result));save()
    save()
    try:
        for action in actions:
            if action=='deliver':
                log('approach',approach(['--slot','2','--execute']))
                log('release_return',handling(['--action','release_return','--execute']))
            else:
                # User confirms EMPTY jaws at HOME; normalize only here.
                s=api('state');near(s['robot']['pose_mm'],g['home'],.05)
                if abs(s['robot']['external_axes']['E1']-7)>.15:
                    result=api('gripper',dict(action='move',e1=7,speed=5))
                    if result.get('recovered') or result.get('gripper_warning'):raise RuntimeError('Uncertain jaw preparation; no retry.')
                    log('empty_jaws7',result)
                log('retrieve',handling(['--action','retrieve','--execute']))
        record['status']='completed_operator_observation_pending'
    except BaseException as exc:
        record.update(status='stopped_or_uncertain',error=str(exc));raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(status=record['status'],record=str(path))),flush=True)
    return record


if __name__=='__main__':main()
