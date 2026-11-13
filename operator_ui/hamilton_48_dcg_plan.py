"""Build a bounded, staged Falcon-48 DCG commissioning plan. No hardware I/O."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np
from hamilton_dynamic_alignment import fit_registration
from hamilton_plate_geometry import dcg_profile

ROOT=Path(__file__).resolve().parent
STAGES=('hover','pickup_lift','transfer_seat','release_return')

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def validated_frame(report, calibration_hash):
    if report.get('serial')!='PRPGJ2494' or report.get('calibration_sha256')!=calibration_hash:
        raise ValueError('Camera registration belongs to another instrument/calibration')
    r=report['frame_fit']
    # Refit evidence; do not trust an editable cached passed flag or matrix.
    return fit_registration(r['camera_fit_mm'],r['controller_fit_mm'],
            r['camera_check_mm'],r['controller_check_mm'],serial=report['serial'],
            calibration_sha256=calibration_hash,evidence=r['reference_evidence'])

def assert_bounds(plan, bounds):
    b={v['channel']:v for v in bounds}
    width=plan['profile']['plate']['grip_body_width_mm']
    clearance=max(plan['profile']['clearance_y_mm'],plan.get('release_clearance_y_mm',0))
    half=(width+2*clearance+3.97)/2
    for point in (plan['source_top_mm'],plan['destination_top_mm']):
        for channel,sign in ((1,1),(2,-1)):
            limit=b[channel]
            if not (limit['x_min']<=point[0]<=limit['x_max'] and
                    limit['y_min']<=point[1]+sign*half<=limit['y_max']):
                raise ValueError('Open gripper exceeds native XY bounds')
            if not limit['z_min']<=plan['grip_z_mm']<=limit['z_max']:
                raise ValueError('Grip exceeds native Z bounds')
            if not limit['z_min']<=plan['traverse_z_mm']<=limit['z_max']:
                raise ValueError('Traverse exceeds native Z bounds')
    if plan['hover_native_z_mm']<max(plan['source_top_mm'][2],plan['destination_top_mm'][2])+30:
        raise ValueError('Hover clearance is too low')

def build_plan(capture_folder,frame_file,plate_export,operator_rim_accepted=False):
    folder=Path(capture_folder)
    measurement=json.loads((folder/'offset_preview.json').read_text())
    manifest=json.loads((folder/'capture.json').read_text())
    if measurement['serial']!='PRPGJ2494' or measurement['model']['labware_id']!=166:
        raise ValueError('Expected PRPGJ2494 and Falcon 48-well geometry')
    calhash=hashlib.sha256((folder/'deck-calibration.json').read_bytes()).hexdigest()
    frame=validated_frame(json.loads(Path(frame_file).read_text()),calhash)
    profile=dcg_profile(plate_export)
    if measurement['repeatability_max_deviation_mm']>.5:
        raise ValueError('Stationary vision estimates are inconsistent')
    for item in measurement['frames']:
        if item['observed_wells']<41 or item['grid_rms_pixels']>2.5:
            raise ValueError('Insufficient observed well-grid evidence')
        if abs(item['angle_crop_deg'])>.5 or item['plane_tilt_deg']>3:
            raise ValueError('Rotation/tilt cannot be corrected by this translation-only transfer')
        if not item['rim']['accepted'] and not operator_rim_accepted:
            raise ValueError('Rim check needs recorded operator inspection')
    centers=np.asarray(measurement['known_plane_centers_export_frame_mm'],float)
    if not np.isfinite(centers).all() or centers.shape!=(3,3): raise ValueError('Expected three finite plate centers')
    rotation=np.asarray(frame['rotation']);translation=np.asarray(frame['translation_mm'])
    native=(rotation@centers.T).T+translation
    source=native.mean(axis=0)
    original=json.loads((ROOT/'reports/hamilton_api/transfer_inspection_20261108T103525584334Z.json').read_text())
    if original['native_serial']!='PRPGJ2494': raise ValueError('Unexpected native geometry evidence')
    sites={v['id']:v for v in original['queries']['PrepGetDeckSiteDefinitions']['sites']}
    def center(site):
        return [site['left_bottom_front_x']+site['length']/2,
                site['left_bottom_front_y']+site['width']/2,
                site['left_bottom_front_z']+profile['plate']['height_mm']]
    nominal=center(sites[6]);destination=center(sites[0])
    correction=source[:2]-np.asarray(nominal[:2])
    if np.linalg.norm(correction)>15: raise ValueError('Offset exceeds the reviewed 15 mm commissioning region')
    # XY comes from vision. Z comes from the actual plate and physical support,
    # never from monocular depth/noisy PnP or a virtual magnet's support.
    source[2]=nominal[2]
    plan=dict(version=1,kind='falcon48_staged_dcg_trial',serial='PRPGJ2494',
        created_at=datetime.now(timezone.utc).isoformat(),capture_at=manifest['captured_at'],
        capture_folder=str(folder.resolve()),camera_calibration_sha256=calhash,
        frame_file=str(Path(frame_file).resolve()),plate_export=str(Path(plate_export).resolve()),
        profile=profile,source_top_mm=source.tolist(),nominal_source_top_mm=nominal,
        destination_top_mm=destination,source_xy_correction_mm=correction.tolist(),
        grip_z_mm=sites[6]['left_bottom_front_z']+profile['native_grip_above_support_mm'],
        hover_native_z_mm=80.,traverse_z_mm=160.,proof_lift_mm=5.,
        fast_scale=20,slow_scale=5,stages=list(STAGES),
        frame_validation='Vendor API cross-check passed; physical hover validation still required',
        frame_check_max_error_mm=max(frame['check_errors_mm']),
        operator_rim_accepted=bool(operator_rim_accepted),
        operator_evidence='User: Rim check is fine, I measured it.' if operator_rim_accepted else None,
        operator_evidence_scope='Rim appearance only; does not certify camera mapping, grip, seating, or unseen changes',
        full_automatic_execution_enabled=False,physical_trial_complete=False,
        source_capture_sha256=manifest['files']['site4_0.png']['sha256'],
        measurement_sha256=hashlib.sha256((folder/'offset_preview.json').read_bytes()).hexdigest(),
        native_sites={str(i):sites[i] for i in (0,6)},
        native_bounds=original['queries']['PrepGetChannelBounds']['bounds'])
    assert_bounds(plan,plan['native_bounds'])
    plan['plan_sha256']=digest(plan)
    return plan

def verify_plan(plan):
    copy=dict(plan);expected=copy.pop('plan_sha256')
    if digest(copy)!=expected: raise ValueError('Plan was edited; rebuild it')
    rebuilt=build_plan(plan['capture_folder'],plan['frame_file'],plan['plate_export'],plan['operator_rim_accepted'])
    for key in rebuilt.keys()-{'created_at','plan_sha256'}:
        if rebuilt[key]!=plan[key]: raise ValueError('Plan evidence changed: '+key)
    assert_bounds(plan,plan['native_bounds'])

def actions(plan,stage):
    """Plain command descriptions for tests, previews and the restricted executor."""
    if stage not in STAGES: raise ValueError('Unknown stage')
    profile=plan['profile'];source=plan['source_top_mm'];destination=plan['destination_top_mm']
    half=(profile['plate']['grip_body_width_mm']+2*profile['clearance_y_mm']+3.97)/2
    open_y={1:source[1]+half,2:source[1]-half}
    if stage=='hover':
        return [dict(command='PickupDCG'),dict(command='RaiseEmpty'),
                dict(command='OpenMove',x=source[0],y=open_y,z=plan['traverse_z_mm']),
                dict(command='Slow'),dict(command='OpenMove',x=source[0],y=open_y,z=plan['hover_native_z_mm'])]
    if stage=='pickup_lift':
        return [dict(command='Slow'),dict(command='PickupPlate',top=source),
                dict(command='MovePlate',top=[*source[:2],source[2]+plan['proof_lift_mm']])]
    if stage=='transfer_seat':
        return [dict(command='Fast'),dict(command='MovePlate',top=[*source[:2],plan['traverse_z_mm']]),
                dict(command='MovePlate',top=[*destination[:2],plan['traverse_z_mm']]),
                dict(command='Slow'),dict(command='MovePlate',top=[*destination[:2],destination[2]+10]),
                dict(command='MovePlate',top=destination)]
    return [dict(command='Slow'),dict(command='DropPlate',top=destination),
            dict(command='RaiseEmpty'),dict(command='Fast'),dict(command='DropTool'),dict(command='Park')]

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture_folder',type=Path);p.add_argument('--frame',type=Path,required=True)
    p.add_argument('--plate-export',type=Path,required=True);p.add_argument('--operator-rim-accepted',action='store_true')
    args=p.parse_args();plan=build_plan(args.capture_folder,args.frame,args.plate_export,args.operator_rim_accepted)
    (args.capture_folder/'staged_transfer_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    print(json.dumps({k:plan[k] for k in ('source_top_mm','source_xy_correction_mm','destination_top_mm','grip_z_mm','hover_native_z_mm','frame_check_max_error_mm','stages','plan_sha256')},indent=2))
