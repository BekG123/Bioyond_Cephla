"""Cellvis scanner -> HOME exchange -> fast rack-clearing Hamilton round trip.

--execute confirms secure held Cellvis plate (or supported in HOME with empty
jaws for --from-home), unchanged fixtures, Hamilton idle/access open/site4 empty,
clear routes including the taught rack pivot, hands clear and E-stop supervised.
No calibration, instrument operation, automatic startup, fault reset or retry.
The plate stays gripped at Hamilton, then is reseated/released in HOME.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

from run_cellvis24_workflow import api,ApiRejected
from run_cellvis24_scanner import confirm
from cellvis24_scanner_return import TRIALS,RUNS,geometry
from cellvis24_workflow import compile_steps
from run_record_io import write_run_record

ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/'operator_ui/reports/plate_session/cellvis24_scanner_hamilton'

def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial-id',help='Completed scanner trial; defaults to the newest scanner attempt, never falls back past a failure.')
    parser.add_argument('--from-home',action='store_true',help='Skip scanner return; start with plate released in accepted HOME clearance.')
    parser.add_argument('--source',type=Path,help='Fresh HOME release receipt, used with --from-home.')
    parser.add_argument('--execute',action='store_true',help='Execute; otherwise offline preview only.')
    parser.add_argument('--direct-hamilton',action='store_true',help='Opt-in shorter candidate with mixed-wrist queue220111; requires publishing and new clearance review.')
    parser.add_argument('--direct-clearance-confirmed',action='store_true',help='Confirm new HOME wrist sweep and direct Hamilton entry corridor are clear.')
    args=parser.parse_args(argv)
    if args.from_home and args.trial_id:parser.error('Use --source with --from-home, not --trial-id.')
    if args.source and not args.from_home:parser.error('--source requires --from-home.')
    if args.direct_clearance_confirmed and not args.direct_hamilton:parser.error('--direct-clearance-confirmed requires --direct-hamilton.')
    if args.direct_hamilton and args.execute and not args.direct_clearance_confirmed:parser.error('Review direct route clearance and pass --direct-clearance-confirmed before execution.')
    return args

def latest_trial():
    candidates=list(TRIALS.glob('*/supervised_grip/proof_lift/scanner_transfer/run.json'))
    if not candidates:raise RuntimeError('No scanner transfer receipt found.')
    return max(candidates,key=lambda p:p.stat().st_mtime).parents[3].name

def reconnect():
    if not api('state')['robot'].get('connected'):api('connect',dict(ip='192.168.201.220'))

def dispatch(path,body,name,timeout=600):
    dispatched=False
    try:
        try:reply=api(path,body)
        except ApiRejected:raise
        except BaseException:dispatched=True;raise
        dispatched=True
        if reply.get('started')!=name:raise RuntimeError('Unexpected dispatcher; no retry.')
        deadline=time.monotonic()+timeout;last=None
        while True:
            seq=api('seq')
            if seq.get('name')!=name:raise RuntimeError('Sequence ownership changed.')
            message=(seq.get('log') or [{}])[-1].get('msg')
            if message!=last:print(message,flush=True);last=message
            if not seq['active']:
                result=seq.get('result') or {}
                if result.get('ok') is not True:raise RuntimeError('Sequence stopped; no retry: '+str(result))
                dispatched=False;return result
            if time.monotonic()>deadline:raise TimeoutError('Completion uncertain; no retry.')
            time.sleep(.5)
    except BaseException:
        if dispatched:
            try:api('seq/stop',{})
            except Exception:pass
        raise

def scanner_phase(ident,phase,supported=False):
    reconnect()
    plan=api('developer/api/cellvis-scanner-return/preview',dict(trial_id=ident,phase=phase))['plan']
    return dispatch('developer/api/cellvis-scanner-return/start',dict(plan=plan,ready=True,path_clear=True,
        plate_supported=supported),'cellvis_scanner_return',180)

def hamilton_roundtrip(source,direct_hamilton=False):
    reconnect()
    plan=api('developer/api/cellvis24-workflow/preview',dict(stations=['hamilton'],cycles=1,source=str(source) if source else None,
        held_hamilton_roundtrip=True,direct_hamilton=direct_hamilton))['plan']
    body=dict(plan=plan,ready=True,path_clear=True,setup_confirmed=True)
    if direct_hamilton:body['direct_clearance_confirmed']=True
    return dispatch('developer/api/cellvis24-workflow/start',body,'cellvis24_workflow')

def main(argv=None):
    args=parse_args(argv);ident=None if args.from_home else args.trial_id or latest_trial()
    g=None if args.from_home else geometry(ident)
    if not args.execute:
        steps=compile_steps(['hamilton'],1,held_hamilton_roundtrip=True,direct_hamilton=args.direct_hamilton)
        print(json.dumps(dict(motion_started=False,trial_id=ident,scanner_return=g,
            holder_target_degrees=90.71661229181757,hamilton_roundtrip=steps,
            finish='Plate released in HOME; no release at Hamilton; no IDLE detour'),indent=2));return
    REPORTS.mkdir(parents=True,exist_ok=True);path=REPORTS/(uuid4().hex+'.json')
    record=dict(status='starting',at=time.time(),trial_id=ident,from_home=args.from_home,steps=[],automatic_retries=False)
    def save():write_run_record(path,record)
    def log(phase,result):
        source=Path(result['record'])
        record['steps'].append(dict(phase=phase,result=result,sha256=hashlib.sha256(source.read_bytes()).hexdigest()));save()
    save()
    try:
        source=args.source
        if not args.from_home:
            result=scanner_phase(ident,'return_home');log('scanner_return',result)
            confirm('Is the plate flat and fully supported in HOME, with both jaws free to open to28, hands clear and E-stop supervised?')
            record['home_support_confirmed_at']=time.time();save()
            result=scanner_phase(ident,'release_home',True);log('release_home',result);source=Path(result['record'])
        result=hamilton_roundtrip(source,args.direct_hamilton);log('held_hamilton_roundtrip',result)
        record.update(status='completed_operator_retention_pending',final=result)
    except BaseException as error:record.update(status='stopped_or_uncertain',error=str(error));raise
    finally:
        record['finished_at']=time.time();save();print(json.dumps(dict(status=record['status'],record=str(path))),flush=True)
    return record

if __name__=='__main__':main()
