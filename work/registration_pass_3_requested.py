"""One additional two-sided pass explicitly requested after pass 2 no-read."""
import json
import time
from pathlib import Path
from retry_dna_registration import Live, scan_register
from cellvis24_scanner_return import sha
from run_record_io import write_run_record

root=Path(__file__).resolve().parents[1]
prior=root/'operator_ui/reports/plate_session/barcode_opposite_trials/1eb629a74b4f4029b2fd0bab283d0348/registration_pass_2_resumed.json'
p=json.loads(prior.read_bytes())
if p['status']!='two_pass_limit_reached_no_barcode_plate_released_HOME':
    raise RuntimeError('Expected completed no-read pass 2.')
source=Path(p['steps'][-1]['result']['release']['record'])
out=prior.with_name('registration_pass_3_requested.json')
r=dict(status='starting',at=time.time(),pass_number=3,additional_pass_limit=1,
    authorization='User explicitly requested try again after completed pass 2; one additional pass only.',
    prior=str(prior),prior_sha256=sha(prior),source=str(source),source_sha256=sha(source),
    calibration_runs=0,purpose='DNA reagents',registration_complete=False,
    station_sequence_started=False,fault_retries=False,steps=[])
with out.open('x') as f:json.dump(r,f)
def save():write_run_record(out,r)
def log(phase,result):
    r['steps'].append(dict(phase=phase,result=result));save()
    print(json.dumps(dict(phase=phase,result=result)),flush=True)
live=Live()
try:
    pickup,result=live.original_scanner(source);log('original_scanner',result)
    registration=scan_register();log('original_scan',registration)
    source,result=live.original_home(pickup);log('original_return_release',result)
    if registration['status']=='no_read':
        pickup,result=live.opposite_scanner(source);log('opposite_scanner',result)
        registration=scan_register();log('opposite_scan',registration)
        source,result=live.opposite_home(pickup);log('opposite_return_release_restore',result)
    if registration['status']=='registered':
        r.update(registration_complete=True,plate_id=registration['plate_id'],station_sequence_started=True);save()
        log('hamilton_squid_cycle',live.stations(source,registration['plate_id']))
        r['status']='registered_and_station_cycle_completed_operator_retention_pending'
    else:r['status']='requested_extra_pass_no_read_plate_released_HOME'
except BaseException as e:
    r.update(status='stopped_or_uncertain',error=str(e));raise
finally:
    r['finished_at']=time.time();save()
    print(json.dumps(dict(status=r['status'],record=str(out))),flush=True)
