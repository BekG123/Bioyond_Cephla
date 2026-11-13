"""One-shot site-6 dry mock with camera-measured dispense targets.

Uses vendor camera calibration and its independently checked native frame.
Keeps the original camera registration marked as NOT physically commissioned.
This is a supervised dry trial, not a general release of vision-guided pipetting.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
import integrated_dry_mock_20261110 as base
from hamilton_plate_offset import detect_grid, register_crop, FALCON48
from hamilton_camera_frame_check import intersect_pixel

ROOT=Path(__file__).resolve().parent
PARENT=ROOT/'reports/integrated_dry_mock_site6_20261110'
OUT=PARENT/'corrected_wells'
CAPTURE=ROOT/'reports/hamilton_api/plate_offset_20261110T080416Z'
AUTH=('Operator confirms plate deliberately off-center but fully seated at site4, '
      'requests adjustment of Hamilton targets and continuation of dry experiment. '
      'No real liquid, source2 A1, six fresh300uL tips site6 A1-A6. '
      'Arm stays Home; no global geometry or safety setting changed.')

def setup():
    base.configure_tip_site(6)
    base.OUT=OUT

def traces(h, start, end):
    found=[]
    for offset in range(0,5000,1000):
        rows=h.call('GET',f'traces?offset={offset}&limit=1000&sources=MNE')['items']
        for row in rows:
            if not start<=row['date']<end:continue
            try:v=json.loads(row['message'])
            except (ValueError,TypeError):continue
            if isinstance(v,list) and v and v[0] in ('Aspirate','Dispense','PickUpTips'):
                found.append(dict(date=row['date'],message=v))
        if not rows or rows[-1]['date']<start:break
    return sorted(found,key=lambda r:r['date'])

def dispense_xy(commands):
    rows=[r['message'][1] for r in commands if r['message'][0]=='Dispense']
    if len(rows)!=6 or any(len(row)!=1 for row in rows):raise ValueError('Expected six single-well dispense commands')
    return np.array([[r[0]['Dispense'][k] for k in ('XPosition','YPosition')] for r in rows],float)

def measure():
    h=base.HamiltonPrep();base.ready(h)
    commands=traces(h,'2026-11-10T07:56:50','2026-11-10T07:58:51')
    nominal=dispense_xy(commands)
    if not np.allclose(nominal,[[16.6+13*i,77.13] for i in range(6)],atol=.01):
        raise ValueError('Original simulated row geometry differs')
    frame=json.loads((CAPTURE/'camera_native_frame_check.json').read_bytes())
    if not frame['passed'] or frame['serial']!='PRPGJ2494':raise ValueError('Frame cross-check failed')
    fit=frame['frame_fit'];rotation=np.array(fit['rotation']);translation=np.array(fit['translation_mm'])
    if max(fit['fit_errors_mm']+fit['check_errors_mm'])>.1:raise ValueError('Frame residual exceeds this trial')
    calibration=json.loads((CAPTURE/'deck-calibration.json').read_bytes())
    if hashlib.sha256((CAPTURE/'deck-calibration.json').read_bytes()).hexdigest()!=frame['calibration_sha256']:
        raise ValueError('Camera calibration changed')
    raw=cv2.imread(str(CAPTURE/'raw.png'),0)
    measurements=[];details=[]
    for index in range(3):
        path=CAPTURE/f'site4_{index}.png';gray=cv2.imread(str(path),0)
        grid=detect_grid(gray,FALCON48);registration=register_crop(gray,raw,calibration)
        # Project actual observed rims rather than filling undetected wells.
        pixels=cv2.perspectiveTransform(grid['centers'][:,None,:],registration['homography'])[:,0,:]
        camera=np.array([intersect_pixel(p,20.19,calibration,registration['camera_matrix']) for p in pixels])
        native=(rotation@camera.T).T+translation
        center_pixel=cv2.perspectiveTransform(grid['transform'][2].reshape(1,1,2),registration['homography']).reshape(2)
        center=rotation@intersect_pixel(center_pixel,20.19,calibration,registration['camera_matrix'])+translation
        shift=center[:2]-[62.1,44.63]
        expected=nominal+shift
        distance=np.linalg.norm(native[None,:,:2]-expected[:,None,:],axis=2)
        nearest=distance.argmin(axis=1)
        if len(set(nearest))!=6 or np.max(distance[np.arange(6),nearest])>1.5:
            raise ValueError('Each destination must have its own directly observed rim near expected grid cell')
        # The affine grid fit pools all visible rims; retain a direct observation
        # check at every requested cell instead of treating noisy Hough centers
        # as six independent metrology references.
        fitted_pixels=np.c_[grid['local'][nearest],np.ones(6)]@grid['transform']
        fitted_full=cv2.perspectiveTransform(fitted_pixels[:,None,:],registration['homography'])[:,0,:]
        fitted_camera=np.array([intersect_pixel(p,20.19,calibration,registration['camera_matrix']) for p in fitted_full])
        selected=((rotation@fitted_camera.T).T+translation)[:,:2]
        direct_error=np.linalg.norm(selected-native[nearest,:2],axis=1)
        if direct_error.max()>.75:raise ValueError('Fitted target disagrees with its visible well rim')
        measurements.append(selected)
        details.append(dict(image=str(path),image_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            target_xy=selected.tolist(),direct_rim_error_mm=direct_error.tolist(),crop_pixel=grid['centers'][nearest].tolist(),grid_rms_px=grid['rms_pixels'],
            registration_rms_px=registration['rms_pixels'],center_xy=center[:2].tolist()))
    measured=np.array(measurements);targets=measured.mean(axis=0)
    jitter=np.linalg.norm(measured-targets,axis=2).max()
    if jitter>.35:raise ValueError(f'Observed well positions vary by {jitter:.3f} mm')
    corrections=targets-nominal
    if np.max(np.linalg.norm(corrections,axis=1))>12:raise ValueError('Outside operator-described offset range')
    if np.any(targets[:,0]<0) or np.any(targets[:,1]<0):raise ValueError('Negative native target')
    report=dict(authorization=AUTH,nominal_xy=nominal.tolist(),target_xy=targets.tolist(),
        offsets=[dict(x=round(x,3),y=round(y,3)) for x,y in corrections],
        max_repeatability_mm=float(jitter),frames=details,capture=str(CAPTURE),
        frame_crosscheck_sha256=hashlib.sha256((CAPTURE/'camera_native_frame_check.json').read_bytes()).hexdigest(),
        original_simulation_commands=commands,operator_confirmed_supported=True,
        physical_pipetting_validated=False,hardware_motion_sent=False)
    base.save(OUT/'measured_targets.json',report)
    print(json.dumps({k:report[k] for k in ('nominal_xy','target_xy','offsets','max_repeatability_mm')}),flush=True)

def check(p):
    report=json.loads((OUT/'measured_targets.json').read_bytes())
    return base.check(p,dispense_offsets=report['offsets'])

def prepare():
    if (OUT/'identity.json').exists():raise RuntimeError('Corrected method already created')
    h=base.HamiltonPrep();base.ready(h)
    old=json.loads((PARENT/'protocol.json').read_bytes())
    offsets=json.loads((OUT/'measured_targets.json').read_bytes())['offsets']
    body=deepcopy(json.loads((PARENT/'preparation.json').read_bytes())['protocol_request'])
    body['name']='DRY MOCK 48 WELL corrected site4 tips6 '+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base.save(OUT/'protocol_request.json',body)
    base.save(OUT/'created.json',h.call('POST','protocols',body))
    found=[p for p in h.call('GET','protocols') if p['name']==body['name']]
    if len(found)!=1:raise RuntimeError('Corrected method identity ambiguous')
    base.save(OUT/'identity.json',found[0]);pid=found[0]['id']
    fresh=h.call('GET',f'protocols/{pid}')
    tip_group=next(p['labwareGroup']['id'] for p in fresh['deck']['positions'] if p['position']==6)
    for i,row in enumerate(base.steps(old,tip_group),1):
        row['dispenseSettings'].update(useOffset=True,offset=offsets[i-1])
        base.save(OUT/f'step_{i}_request.json',row)
        base.save(OUT/f'step_{i}_response.json',h.call('POST',f'protocols/{pid}/step',row))
    try:
        validation=h.call('GET',f'protocols/validate/{pid}')
    except Exception as error:
        base.save(OUT/'validation_failure.json',dict(error=str(error),protocol_id=pid,hardware_motion_sent=False))
        raise
    base.save(OUT/'validation.json',validation)
    p=h.call('GET',f'protocols/{pid}');base.save(OUT/'protocol.json',p);check(p)
    print(json.dumps(dict(prepared=True,protocol_id=pid,hash=base.digest(p))),flush=True)

def record_block():
    """Record the rejected first preparation without retrying a validation/start."""
    h=base.HamiltonPrep();state=base.ready(h)
    identity=json.loads((OUT/'identity.json').read_bytes())
    p=h.call('GET',f"protocols/{identity['id']}")
    if p['isValid'] is not False:raise RuntimeError('Expected rejected method')
    from three_machine_dry_run_20261110 import arm_home
    robot=arm_home()
    base.save(OUT/'blocked_outcome.json',dict(status='blocked_by_vendor_protocol_validation',
        protocol_id=p['id'],protocol=p,hamilton=state,arm=robot,authorization=AUTH,
        error='Offset exceeds maximum for labware P48w800kmmtjFAL.',
        measured_targets=json.loads((OUT/'measured_targets.json').read_bytes()),
        reason='Protocol dispense offsets are constrained within labware wells; the public deck-position schema has no plate XYZ/yaw transform.',
        next_implementation='A separately validated plate-pose-aware execution path, with full plate geometry and unchanged instrument limits.',
        original_protocol_preserved=True,physical_pipetting_started=False,squid_imaging_started=False,
        plate_location='Hamilton site4; intentionally off-center and fully seated per operator',
        jaw_release_mm=7,at=time.time()))
    print('Rejected corrected protocol recorded; arm Home, Hamilton Idle, no physical pipetting.',flush=True)

def verify_compiled():
    h=base.HamiltonPrep()
    result=json.loads((OUT/'simulation/result.json').read_bytes())
    # API local timestamps are Pacific time; trace timestamps are UTC.
    from zoneinfo import ZoneInfo
    start=datetime.fromisoformat(result['startTime']).replace(tzinfo=ZoneInfo('America/Los_Angeles')).astimezone(timezone.utc)
    end=datetime.fromisoformat(result['endTime']).replace(tzinfo=ZoneInfo('America/Los_Angeles')).astimezone(timezone.utc)
    commands=traces(h,start.isoformat().replace('+00:00','Z'),end.isoformat().replace('+00:00','Z'))
    actual=dispense_xy(commands)
    report=json.loads((OUT/'measured_targets.json').read_bytes());expected=np.array(report['target_xy'])
    errors=np.linalg.norm(actual-expected,axis=1)
    record=dict(actual_xy=actual.tolist(),expected_xy=expected.tolist(),errors_mm=errors.tolist(),
        passed=bool(np.max(errors)<.05),commands=commands,job_id=result['id'],hardware_motion_sent=False)
    base.save(OUT/'compiled_target_check.json',record)
    if not record['passed']:raise RuntimeError('Vendor offset signs/units do not reproduce measured wells')
    print(json.dumps(dict(compiled_targets_verified=True,max_error_mm=float(errors.max()))),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['measure','prepare','simulate','verify-compiled','restore-connection','record-block'])
    args=parser.parse_args();setup()
    dict(measure=measure,prepare=prepare,simulate=lambda:base.simulate(protocol_check=check),
         **{'verify-compiled':verify_compiled,'restore-connection':lambda:base.restore_connection(protocol_check=check),
            'record-block':record_block})[args.action]()
