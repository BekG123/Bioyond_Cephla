"""Accepted Cellvis P24-1.5H-N projected calibration, pickup and scanner route.

Preview by default. --execute confirms empty jaws, plate seated lid-off in
HOME, unchanged fixtures, clear pickup and loaded scanner sweep, hands clear
and supervised E-stop. Start at IDLE with healthy already-running Auto/Lua.
Pauses for visual alignment and proof-lift retention checks unless --continuous
uses the accepted setup and standing supervision without fresh inspections. No automatic
startup, fault reset, retries, barcode trigger, release or return from scanner.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

from run_cellvis24_workflow import api, ApiRejected, main as calibrate
from cellvis24_scanner_pickup import grip_trial, proof_lift, trial_source
from run_record_io import write_run_record

ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/'operator_ui/reports/plate_session/cellvis24_scanner_workflows'


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--full-calibration',action='store_true',help='Fresh shared projected-disk calibration, alignment and descent before pickup.')
    mode.add_argument('--trial-id',help='Continue a fresh completed open-jaw Cellvis trial, before its first grip attempt.')
    parser.add_argument('--execute',action='store_true',help='Run the supervised workflow; without this flag, print the route only.')
    parser.add_argument('--continuous',action='store_true',help='Use the accepted setup without interactive inspection pauses; retain all runtime checks.')
    args=parser.parse_args(argv)
    if args.trial_id:
        try:trial_source(args.trial_id)
        except ValueError as error:parser.error(str(error))
    return args


def confirm(message):
    answer=input(message+'\nType yes to continue, or anything else to stop: ').strip().lower()
    if answer!='yes':raise RuntimeError('Operator stopped the workflow; no next movement sent.')


def scanner_transfer(ident):
    # Inspection may outlast the host's ordinary idle disconnect. Reconnect
    # transport only; preview still checks enabled/running Auto and the grip.
    if not api('state')['robot'].get('connected'):api('connect',{'ip':'192.168.201.220'})
    plan=api('developer/api/cellvis-scanner/preview',dict(trial_id=ident))['plan']
    dispatched=False
    try:
        try:
            reply=api('developer/api/cellvis-scanner/start',dict(plan=plan,plate_secure=True,
                loaded_path_clear=True,estop_supervised=True))
        except ApiRejected:raise
        except BaseException:
            dispatched=True
            raise
        dispatched=True
        if reply.get('started')!='cellvis_scanner_transfer':raise RuntimeError('Unexpected scanner dispatcher.')
        deadline=time.monotonic()+180;last=None
        while True:
            seq=api('seq')
            if seq.get('name')!='cellvis_scanner_transfer':raise RuntimeError('Scanner task ownership changed.')
            message=(seq.get('log') or [{}])[-1].get('msg')
            if message!=last:print(message,flush=True);last=message
            if not seq['active']:
                result=seq.get('result') or {}
                if result.get('ok') is not True:raise RuntimeError('Scanner transfer failed; no retry: '+str(result))
                dispatched=False
                return result
            if time.monotonic()>deadline:raise TimeoutError('Scanner completion uncertain; no retry.')
            time.sleep(.5)
    except BaseException:
        if dispatched:
            try:api('seq/stop',{})
            except Exception:pass
        raise


def preview(args):
    from gripper_closure import closure_plan
    from scanner_empty_route import TARGET
    return dict(motion_started=False,full_calibration=args.full_calibration,trial_id=args.trial_id,
        calibration='Shared projected disks; Cellvis 4x6 grid; measured XY/yaw; Z75.72 mm',
        grip=closure_plan(28.,3.9),proof_lift=dict(mm=5,speed=5),
        scanner=dict(clearance_z_mm=300,target=TARGET,speed=137,queues=1),
        inspections=[] if args.continuous else ['Even jaw spacing, correct contact height and clear proof lift',
                     'Plate level/secure after proof lift; loaded scanner sweep clear'],
        finish='Plate held at scanner; no release or barcode trigger',automatic_retries=False)


def main(argv=None):
    args=parse_args(argv)
    if not args.execute:
        print(json.dumps(preview(args),indent=2));return
    REPORTS.mkdir(parents=True,exist_ok=True)
    path=REPORTS/(uuid4().hex+'.json')
    record=dict(status='starting',at=time.time(),request=vars(args),steps=[],operator_observations=[],
        automatic_retries=False,scanner_retention='not_yet_observed',
        inspection_mode='accepted_setup_no_fresh_inspection' if args.continuous else 'interactive')
    def save():write_run_record(path,record)
    def add_receipt(phase,receipt):
        receipt=Path(receipt)
        record['steps'].append(dict(phase=phase,record=str(receipt),sha256=hashlib.sha256(receipt.read_bytes()).hexdigest()))
        save()
    save()
    try:
        if args.full_calibration:
            result=calibrate(['--projected-calibration-trial','--execute'])
            if result.get('status')!='awaiting_open_claw_inspection':raise RuntimeError('Expected completed open-jaw Cellvis calibration.')
            ident=Path(result['record']).parent.name
        else:ident=args.trial_id
        source=trial_source(ident)
        record['trial_id']=ident;add_receipt('calibration',source)
        if not args.continuous:
            confirm('Inspect without moving the arm: are the jaws evenly spaced at the correct gripping height, the plate flat, and the 5 mm upward path clear, with hands clear and E-stop supervised?')
            record['operator_observations'].append(dict(at=time.time(),alignment_and_proof_lift_clear=True));save()
        add_receipt('grip',grip_trial(ident,execute=True))
        add_receipt('proof_lift',proof_lift(ident))
        if not args.continuous:
            confirm('Did the plate lift level without slipping? Is the loaded route up to Z300, across/turn to the scanner, and down to Z189.16 clear, with hands clear and E-stop supervised?')
            record['operator_observations'].append(dict(at=time.time(),proof_lift_secure=True,scanner_route_clear=True));save()
        result=scanner_transfer(ident);add_receipt('scanner',result['record'])
        record.update(status='completed_operator_retention_pending',final=result)
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(status=record['status'],record=str(path))),flush=True)
    print('Arrived with the plate held. Inspect retention before recording physical success. No release or return was commanded.',flush=True)
    return record


if __name__=='__main__':main()
