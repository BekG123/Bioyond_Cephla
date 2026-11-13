"""Shared projected-disk calibration with Cellvis geometry and taught grasp.

Accepted pickup retains its fixed endpoint. Explicit projected trials carry
the measured target into alignment/descent and stop open for inspection.
"""
import hashlib
import json
import math
import time
from pathlib import Path

from autonomy import TransferError
from scope_step_trial import near

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'
REFERENCE=ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis24_camera_reference_v3.json'
RIM_SAMPLE_SPAN=(.25,.75)
RIM_TANGENT_RADIUS=2
ACCEPTED_SEQUENCE=ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis24_accepted_calibration_sequence_v1.json'
ACCEPTED_SEQUENCE_SHA='4a21771cc58c2671e0cd86ac8d54fcc9a45c8f12877eeaaa9f696546ccef3b6c'
IDLE=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
OBSERVATION=dict(X=279.379,Y=25.829,Z=289.129,Rz=-3.88)


def reference():
    from cellvis24_image_pipeline import PIPELINE_ID,JPEG_QUALITY
    d=json.loads(REFERENCE.read_bytes())
    if d.get('schema_version')!=3 or tuple(d.get('rim_sample_span',[]))!=RIM_SAMPLE_SPAN or d.get('image_pipeline',{}).get('id')!=PIPELINE_ID or d['image_pipeline'].get('jpeg_quality')!=JPEG_QUALITY:
        raise TransferError('Cellvis reference image pipeline mismatch.')
    if d.get('rim_tangent_radius')!=RIM_TANGENT_RADIUS or d.get('rim_line_fit')!='gm-irls-1.5px-v1':
        raise TransferError('Cellvis reference rim smoothing mismatch.')
    for item in d['files'].values():
        if hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()!=item['sha256']:
            raise TransferError('Cellvis camera reference changed: '+item['path'])
    return d


def compile_steps():
    """Exact accepted camera -> shared alignment -> descent -> grip sequence.

    Vision verifies placement; it never adds an experimental XY/yaw correction.
    The small versioned profile is portable without the large historical logs.
    """
    from cellvis24_squid_route import geometry
    raw=ACCEPTED_SEQUENCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ACCEPTED_SEQUENCE_SHA:
        raise TransferError('Accepted Cellvis calibration sequence changed.')
    d=json.loads(raw);steps=d['steps'];g=geometry()
    for label,key in [('Final open-jaw descent','seat'),('Proof lift 5 mm at speed 5','proof'),('Released HOME clearance','clearance')]:
        if next(s for s in steps if s['label']==label)['points'][-1]!=g[key]:
            raise TransferError('Cellvis handling geometry differs from accepted calibration: '+key)
    return steps


def implementation_binding():
    """Invalidate previews after changes to perception, mapping or execution."""
    paths=('operator_ui/projected_plate_calibration.py','operator_ui/cellvis24_calibration.py',
           'operator_ui/cellvis24_observation.py','operator_ui/cellvis24_image_pipeline.py',
           'operator_ui/cellvis24_workflow.py','Pick and Hold/Align/plate_pose/grid_preview.py',
           'Pick and Hold/Align/plate_pose/rim_edges.py')
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}


def projected_profile():
    from projected_plate_calibration import PlateCalibrationProfile
    d=reference();base=d['raw_target']
    target=next(s['target'] for s in compile_steps() if s['kind']=='align')
    return PlateCalibrationProfile(
        plate_id=d['plate'],rows=4,columns=6,
        reference_target=tuple(base[k] for k in ('x','y','rz')),
        taught_endpoint=tuple(target[k] for k in ('x','y','z_calibrated','rz')),
        grip_e1_mm=3.9,min_wells=20)


def projected_solution(measurements):
    from projected_plate_calibration import solve
    return solve(measurements,projected_profile())


def projected_trial_steps(solution=None):
    """Same accepted approach template; no closure/lift or station handling.

    Before acquisition the preview contains the nominal taught endpoint.
    After acquisition, each remaining XY/yaw uses ONE resolved target. Z and
    the approach speeds remain the accepted Cellvis values.
    """
    steps=[]
    for step in compile_steps():
        if step['kind']=='jaws':break
        steps.append(step)
    if solution is None:return steps
    if solution.get('grip_authorized') is not False or solution.get('physical_acceptance')!='pending':
        raise TransferError('Projected trial cannot grant grip acceptance.')
    endpoint=solution['endpoint']
    for step in steps:
        if step['kind']=='align':
            step['target']=dict(x=endpoint['X'],y=endpoint['Y'],rz=endpoint['Rz'],z_calibrated=endpoint['Z'])
        elif step['kind']=='queue' and step['label'] in ('Fast open-jaw approach','Final open-jaw descent'):
            step['points']=[dict(p,X=endpoint['X'],Y=endpoint['Y'],Rz=endpoint['Rz']) for p in step['points']]
    return steps


def evaluate(measurements):
    """Diagnostic decision; preserve every burst and the existing reuse limits."""
    from cellvis24_observation import summarize
    d=reference();baseline=d['raw_target'];summary=summarize(measurements)
    result=dict(summary,accepted_reference_reused=False,depth_estimated=False,bursts=[],
                limits=dict(xy_mm=d['reuse_xy_mm'],yaw_deg=d['reuse_yaw_deg'],calibration_error_mm=.75))
    def fail(code,message):
        return dict(result,ok=False,code=code,message=message)
    if not summary['stationary_checks_passed']:
        return fail('unstable_measurements','Cellvis camera measurements are unstable; no descent.')
    for m in measurements:
        t=m['target'];values=[t['x'],t['y'],t['rz'],m['grid_rmse_px'],*m['error_xy_mm']]
        if not all(math.isfinite(v) for v in values):return fail('invalid_measurements','Nonfinite Cellvis camera result.')
        if not 20<=m['measured_wells']<=24 or m['grid_rmse_px']>8:
            return fail('grid_rejected','Cellvis 4x6 well-grid check failed; no descent.')
        shift=math.hypot(t['x']-baseline['x'],t['y']-baseline['y'])
        yaw=abs((t['rz']-baseline['rz']+180)%360-180)
        result['bursts'].append(dict(shift_mm=shift,yaw_delta_deg=yaw,calibration_error_mm=math.hypot(*m['error_xy_mm'])))
    shifts=[b['shift_mm'] for b in result['bursts']];max_shift=max(shifts)
    max_yaw=max(b['yaw_delta_deg'] for b in result['bursts']);max_error=max(b['calibration_error_mm'] for b in result['bursts'])
    result.update(max_shift_mm=max_shift,max_yaw_delta_deg=max_yaw,max_calibration_error_mm=max_error,
                  xy_limit_straddled=min(shifts)<=d['reuse_xy_mm']<max_shift)
    if max_shift>d['reuse_xy_mm'] or max_yaw>d['reuse_yaw_deg'] or max_error>.75:
        return fail('reference_mismatch',
            f"Cellvis camera reference check failed: maximum estimated target shift {max_shift:.3f} mm (limit {d['reuse_xy_mm']:.3f}), "
            f"yaw {max_yaw:.3f} degrees (limit {d['reuse_yaw_deg']:.3f}), center error {max_error:.3f} mm (limit 0.750). "
            'No descent; inspect the saved measurements and seating.')
    return dict(result,ok=True,accepted_reference_reused=True)


def assess(measurements):
    result=evaluate(measurements)
    if not result['ok']:raise TransferError(result['message'])
    return result


def capture(cam,check,folder,save_result,*,require_fixed_reference=True):
    import cv2
    from cellvis24_observation import measure,teach
    from cellvis24_image_pipeline import prepare_raw,median5,metadata
    d=reference();seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
    disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes())
    cfg=next(c for c in teach._configs() if c['name']=='Wide')
    ok,_=teach.selftest()
    if not ok:raise TransferError('Vendor Wide math self-test failed.')
    measurements=[];result=dict(bursts=[],image_pipeline=metadata(),rim_sample_span=list(RIM_SAMPLE_SPAN),rim_tangent_radius=RIM_TANGENT_RADIUS)
    for i in range(3):
        frames=[];hashes=[]
        for j in range(5):
            s,_=check(True,True);near(s['pose_mm'],OBSERVATION,.05)
            frame=cam.snap()  # Sole camera owner, guaranteed fresh acquisition.
            s,_=check(True,True);near(s['pose_mm'],OBSERVATION,.05)
            hashes.append(hashlib.sha256(frame.tobytes()).hexdigest());frames.append(prepare_raw(frame))
            if not cv2.imwrite(str(folder/f'calibration_{i}_{j}.png'),frame):raise OSError('Cannot save camera evidence.')
            time.sleep(.1)
        if len(set(hashes))<3:raise TransferError('Cellvis camera repeated stale frames.')
        median=median5(frames)
        if not cv2.imwrite(str(folder/f'prepared_median_{i}.png'),median):raise OSError('Cannot save prepared camera evidence.')
        burst=dict(hashes=hashes,prepared_median_sha256=hashlib.sha256(median.tobytes()).hexdigest())
        result['bursts'].append(burst);save_result(result)
        try:
            m=measure(median,seed,disks,OBSERVATION,cfg,rim_sample_span=d['rim_sample_span'],rim_tangent_radius=d['rim_tangent_radius'])
        except Exception as error:
            burst.update(status='rejected',error=str(error));save_result(result)
            raise
        measurements.append(m);burst['measurement']=m;save_result(result)
    result['assessment']=evaluate(measurements)
    try:
        result['projected_solution']=projected_solution(measurements)
    except TransferError as error:
        result['projected_solution_error']=str(error)
        save_result(result)
        if not require_fixed_reference:raise
    save_result(result)
    if require_fixed_reference and not result['assessment']['ok']:raise TransferError(result['assessment']['message'])
    return result
