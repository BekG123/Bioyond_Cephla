"""Approved empty-HOME preparation before retrieval; no arm route or recovery."""
import hashlib
import json
import math
from pathlib import Path
import re
import time

from autonomy import TransferError
from calibration_e2 import accepted, TARGET_DEGREES
from cellvis_recovery_handoff import restore_segments
from home_hamilton_exchange import native, holder_restore_targets
from scope_step_trial import near, preflight
from run_record_io import write_run_record

OUTPUT=Path(__file__).parent/'reports/plate_session/hotel_holder_preparation'


def preparation(angle):
    targets=holder_restore_targets(angle,TARGET_DEGREES)
    return None if accepted(angle) else dict(target=TARGET_DEGREES,targets=targets)


def digest(spec):
    return hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def execute(run,backend,spec,require):
    """Called only by the human-confirmed composition, after spec verification."""
    if not re.fullmatch('[0-9a-f]{32}',run.run_id):raise TransferError('Invalid preparation run ID.')
    service=backend.s;g=spec['geometry'];p=spec['holder_preparation']
    if p is None or p!=preparation(spec['axes']['E2']):raise TransferError('Holder preparation changed.')
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/(run.run_id+'.json')
    record=dict(status='checking',spec_sha256=digest(spec),steps=[],motion_sent=False,
        payload='operator_confirmed_empty',home='operator_confirmed_empty',automatic_retries=False)
    with path.open('x',encoding='utf-8') as stream:json.dump(record,stream)
    def save():write_run_record(path,record)
    def check(expected=None,open_jaws=True):
        if run.stopped():raise TransferError('Stopped during HOME holder preparation.')
        s=preflight(service);n=native(service);axes=n['external_axes']
        if n['moving']:raise TransferError('Arm must remain stationary during holder preparation.')
        if spec['slot']==1:
            from hotel_home_start import check_home_start
            check_home_start(s['pose_mm'],g['home'])
        else:near(s['pose_mm'],g['home'],.05)
        near(s['pose_mm'],spec['start'],.05)  # No arm drift during holder rotation.
        if backend.params()!=g['cfg'] or not service.envelope_enabled or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
            raise TransferError('Holder preparation configuration/workspace changed.')
        if any(not math.isfinite(axes[k]) for k in ('E1','E2')) or abs(axes['E2'])>360:
            raise TransferError('Invalid holder/jaw feedback.')
        if open_jaws and abs(axes['E1']-28)>.07:raise TransferError('Holder rotation requires empty jaws open to 28 mm.')
        if expected is not None and abs(axes['E2']-expected)>.1:
            raise TransferError('Holder changed or arrival mismatch; no retry.')
        return s,n
    def dispatch():record.update(motion_sent=True);save()
    def segment(item):record['steps'].append(item);save()
    try:
        _,n=check(spec['axes']['E2'],False)
        if abs(n['external_axes']['E1']-spec['axes']['E1'])>.05:
            raise TransferError('Jaw start changed; request a fresh plan.')
        if abs(n['external_axes']['E1']-28)>.07:
            run.say('Open empty jaws to 28 mm before positioning the HOME holder.')
            dispatch();result=require(service.move_gripper(28,5))
            check(spec['axes']['E2']);segment(dict(kind='open_empty_jaws',result=result))
        restore_segments(run,service,p['targets'],spec['axes']['E2'],check,require,dispatch,segment)
        for _ in range(3):
            s,n=check(TARGET_DEGREES)
            if not accepted(n['external_axes']['E2']):
                raise TransferError('Original holder angle not verified; no retrieval or retry.')
            time.sleep(.1)
        record.update(status='completed',final=s,final_native=n)
        return dict(ok=True,record=str(path),kind='prepared_hotel_holder')
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        if record['motion_sent']:
            try:record['stop']=service.program('stop')
            except Exception as stop:record['stop_error']=str(stop)
        raise
    finally:record['finished_at']=time.time();save()


def verify_receipt(run,spec,prior):
    path=OUTPUT/(run.run_id+'.json')
    if not prior or prior.get('kind')!='prepared_hotel_holder' or Path(prior.get('record','')).resolve()!=path.resolve():
        raise TransferError('Completed holder preparation receipt required.')
    data=json.loads(path.read_bytes())
    if data.get('status')!='completed' or data.get('spec_sha256')!=digest(spec) or not 0<=time.time()-data['finished_at']<=900:
        raise TransferError('Holder preparation failed, changed or expired.')
    return data
