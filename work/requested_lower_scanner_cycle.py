"""Explicit lower-scanner trial, then one registered Hamilton/Squid cycle."""
import argparse
import json
import time
from pathlib import Path
from uuid import uuid4
from retry_dna_registration import Live,scan_register
from run_record_io import write_run_record

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',required=True,type=Path)
parser.add_argument('--execute',action='store_true')
parser.add_argument('--lower-clearance-confirmed',action='store_true')
args=parser.parse_args()
if not args.execute:
    print(json.dumps(dict(motion_started=False,scanner_target=dict(X=80.88,Y=-143.51,Z=163.76,Rz=-1.63),
        calibration_runs=0,triggers_per_side=5,cycles=1,order=['scan original side','scan opposite side if no read',
        'return and release in HOME','Hamilton drop-off/retrieval','Squid drop-off/retrieval','HOME'],
        stations_require_decoded_barcode=True)))
    raise SystemExit(0)
if not args.lower_clearance_confirmed:parser.error('Confirm the newly lowered loaded scanner approach before execution.')
root=Path(__file__).resolve().parents[1]
folder=root/'operator_ui/reports/plate_session/dna_plate_registration';folder.mkdir(parents=True,exist_ok=True)
out=folder/('lower_scanner_'+uuid4().hex+'.json')
r=dict(status='starting',at=time.time(),source=str(args.source.resolve()),scanner_z=163.76,
    lower_approach_clearance_confirmed=True,calibration_runs=0,cycles=1,steps=[],automatic_fault_retries=False)
def save():write_run_record(out,r)
def log(phase,result):
    r['steps'].append(dict(phase=phase,at=time.time(),result=result));save()
    print(json.dumps(dict(phase=phase,result=result)),flush=True)
with out.open('x') as f:json.dump(r,f)
try:
    live=Live(scanner_z=163.76)
    pickup,result=live.original_scanner(args.source);log('original_scanner',result)
    registration=scan_register();log('original_scan',registration)
    source,result=live.original_home(pickup);log('original_return_release',result)
    if registration['status']=='no_read':
        pickup,result=live.opposite_scanner(source);log('opposite_scanner',result)
        registration=scan_register();log('opposite_scan',registration)
        source,result=live.opposite_home(pickup);log('opposite_return_release',result)
    if registration['status']=='registered':
        if registration['plate_id']!='SU-PRKL-P-2611-0001':
            raise RuntimeError('Barcode differs from the expected registered plate; station handling not started.')
        r.update(registration_complete=True,plate_id=registration['plate_id']);save()
        log('hamilton_home_squid_home',live.stations(source,registration['plate_id']))
        r.update(status='completed_operator_retention_pending',completed_cycles=1)
    else:r.update(status='no_read_both_sides_plate_released_HOME',completed_cycles=0)
except BaseException as e:r.update(status='stopped_or_uncertain',error=str(e));raise
finally:
    r['finished_at']=time.time();save()
    print(json.dumps(dict(status=r['status'],record=str(out))),flush=True)
