"""User-requested single handling cycle after the completed empty recovery.

No calibration. Five triggers per side, one opposite-side attempt on no-read.
Stop on any uncertain hardware outcome. No silent retry or fault recovery.
"""
import json
import time
from pathlib import Path
from uuid import uuid4
from run_cellvis24_scanner_hamilton import reconnect,api,dispatch
from retry_dna_registration import Live,scan_register
from run_record_io import write_run_record

root=Path(__file__).resolve().parents[1]
recovery=root/'operator_ui/reports/plate_session/empty_home_recovery/5aa1280c44754017bf445f66576a9c66.json'
folder=root/'operator_ui/reports/plate_session/dna_plate_registration'
folder.mkdir(parents=True,exist_ok=True)
output=folder/('requested_after_recovery_'+uuid4().hex+'.json')
r=dict(status='starting',at=time.time(),recovery=str(recovery),cycles=1,calibration_runs=0,
       scan_triggers_per_side=5,purpose='DNA reagents',steps=[],automatic_fault_retries=False,
       observation_basis='Operator confirmed plate reseated in HOME, jaws empty, obstruction removed and requested this cycle; no new visual retention observation claimed.')
def save():write_run_record(output,r)
def log(phase,result):
    r['steps'].append(dict(phase=phase,at=time.time(),result=result));save()
    print(json.dumps(dict(phase=phase,result=result)),flush=True)
with output.open('x') as f:json.dump(r,f)
try:
    reconnect()
    p=api('developer/api/cellvis-recovery-handoff/preview',dict(recovery=str(recovery),trial_id='6b66922bf37445cfbdc94711ac8f9b54'))['plan']
    result=dispatch('developer/api/cellvis-recovery-handoff/start',dict(plan=p,plate_seated=True,
        empty_gripper=True,rotation_clear=True,estop_supervised=True),'cellvis_recovery_handoff',180)
    log('restore_released_holder',result)
    live=Live();pickup,result=live.original_scanner(result['record']);log('original_scanner',result)
    registration=scan_register();log('original_scan',registration)
    source,result=live.original_home(pickup);log('original_return_release',result)
    if registration['status']=='no_read':
        pickup,result=live.opposite_scanner(source);log('opposite_scanner',result)
        registration=scan_register();log('opposite_scan',registration)
        source,result=live.opposite_home(pickup);log('opposite_return_release',result)
    if registration['status']=='registered':
        if registration['plate_id']!='SU-PRKL-P-2611-0001':
            raise RuntimeError('Barcode differs from the previously registered plate; returned HOME, station cycle not started.')
        r.update(registration_complete=True,plate_id=registration['plate_id']);save()
        result=live.stations(source,registration['plate_id']);log('hamilton_home_squid_home',result)
        r.update(status='completed_operator_retention_pending',completed_cycles=1)
    else:r.update(status='no_read_both_sides_plate_released_HOME',completed_cycles=0)
except BaseException as e:
    r.update(status='stopped_or_uncertain',error=str(e));raise
finally:
    r['finished_at']=time.time();save()
    print(json.dumps(dict(status=r['status'],record=str(output))),flush=True)
