"""One barcode-gated Cellvis handling cycle; no calibration or instrument jobs.

--execute asserts the unchanged, supervised, clear setup described by the saved
cellvis24-scan-station-cycle-v1 skill. This is a handling-only executor: a
scheduler must not use it to overlap pipetting/imaging with immediate retrieval.
"""
import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from retry_dna_registration import Live
from run_dna_plate_registration import scan_until_decoded
from run_record_io import write_run_record

REPORTS=Path(__file__).parent/'reports/plate_session/dna_plate_registration'


def register(purpose):
    from plate_registry import PlateRegistry
    try:scan,receipt,count=scan_until_decoded(5,1.)
    except RuntimeError as e:
        if str(e)=='No read after 5 triggers; plate still held at the scanner.':
            return dict(status='no_read',triggers=5)
        raise
    saved=scan.get('plate_registry',{})
    if saved.get('saved') is not True:raise RuntimeError('Barcode decoded but registration was not saved.')
    plate=PlateRegistry().update(saved['plate_id'],saved['revision'],dict(experiment=purpose),
        'User-stated intended purpose, not measured contents; scanner receipt '+str(receipt))
    return dict(status='registered',plate_id=plate['plate_id'],triggers=count,receipt=str(receipt))


def run_cycle(source,*,purpose,expected_plate_id=None,live=None,scan=None):
    if not isinstance(purpose,str) or not purpose.strip():raise ValueError('Provide the intended plate purpose.')
    REPORTS.mkdir(parents=True,exist_ok=True);out=REPORTS/('registered_cycle_'+uuid4().hex+'.json')
    r=dict(status='starting',at=time.time(),source=str(Path(source).resolve()),purpose=purpose,
        expected_plate_id=expected_plate_id,scanner_z=163.76,cycles=1,calibration_runs=0,steps=[],
        automatic_fault_retries=False,handling_only=True)
    def save():write_run_record(out,r)
    def log(phase,result):
        r['steps'].append(dict(phase=phase,at=time.time(),result=result));save()
        print(json.dumps(dict(phase=phase,result=result)),flush=True)
    live=live or Live(scanner_z=163.76);scan=scan or (lambda:register(purpose))
    with out.open('x') as f:json.dump(r,f)
    try:
        pickup,result=live.original_scanner(source);log('original_scanner',result)
        registration=scan();log('original_scan',registration)
        source,result=live.original_home(pickup);log('original_return_release',result)
        if registration['status']=='no_read':
            pickup,result=live.opposite_scanner(source);log('opposite_scanner',result)
            registration=scan();log('opposite_scan',registration)
            source,result=live.opposite_home(pickup);log('opposite_return_release',result)
        if registration['status']=='registered':
            if expected_plate_id and registration['plate_id']!=expected_plate_id:
                raise RuntimeError('Unexpected barcode; plate returned HOME, station handling not started.')
            r.update(registration_complete=True,plate_id=registration['plate_id']);save()
            result=live.stations(source,registration['plate_id']);log('hamilton_home_squid_home',result)
            r.update(status='completed_operator_retention_pending',completed_cycles=1)
        else:r.update(status='no_read_both_sides_plate_released_HOME',completed_cycles=0)
    except BaseException as e:r.update(status='stopped_or_uncertain',error=str(e));raise
    finally:
        r['finished_at']=time.time();save()
        print(json.dumps(dict(status=r['status'],record=str(out))),flush=True)
    return dict(r,record=str(out))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True,help='Fresh unused completed HOME release receipt.')
    p.add_argument('--purpose',required=True,help='User-declared intended contents/purpose; not inferred from barcode.')
    p.add_argument('--expected-plate-id',help='If supplied, stop before station handling on identity mismatch.')
    p.add_argument('--execute',action='store_true')
    a=p.parse_args(argv)
    if not a.execute:
        print(json.dumps(dict(motion_started=False,calibration_runs=0,cycles=1,scanner_z=163.76,
            scan_limit_per_side=5,stations_require_decode=True,handling_only=True,
            finish='Plate released in HOME, original holder orientation, empty jaws28')))
        return
    return run_cycle(a.source,purpose=a.purpose,expected_plate_id=a.expected_plate_id)


if __name__=='__main__':main()
