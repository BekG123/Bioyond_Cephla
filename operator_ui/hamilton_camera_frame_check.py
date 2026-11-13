"""Cross-check camera coordinates against vendor site crops and native site geometry.

GET camera requests only. This is a software/frame cross-check, not an
independent physical positioning test. Its result can prepare a hover trial.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from hamilton_prep import HamiltonPrep
from hamilton_plate_offset import register_crop
from hamilton_dynamic_alignment import fit_registration

ROOT=Path(__file__).resolve().parent
SITES={4:6,3:0,8:7,6:3,2:1,5:4}

def intersect_pixel(pixel, z, calibration, camera_matrix):
    rotation=np.asarray(calibration['Rotation']['Data'],float)
    translation=np.asarray(calibration['Translation']['Data'],float).reshape(3)
    origin=-rotation.T@translation
    ray=rotation.T@np.linalg.inv(camera_matrix)@np.r_[pixel,1]
    if abs(ray[2])<1e-6: raise ValueError('Ray parallel to reference plane')
    return origin+(z-origin[2])/ray[2]*ray

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture_folder',type=Path)
    p.add_argument('--capture',action='store_true')
    args=p.parse_args();folder=args.capture_folder
    calibration=json.loads((folder/'deck-calibration.json').read_text())
    calibration_hash=hashlib.sha256((folder/'deck-calibration.json').read_bytes()).hexdigest()
    raw=cv2.imread(str(folder/'raw.png'),0)
    evidence=json.loads((ROOT/'reports/hamilton_api/transfer_inspection_20261108T103525584334Z.json').read_text())
    if evidence['native_serial']!='PRPGJ2494': raise RuntimeError('Wrong native geometry evidence')
    native={v['id']:v for v in evidence['queries']['PrepGetDeckSiteDefinitions']['sites']}
    if args.capture:
        h=HamiltonPrep();state=h.preflight(initialized=True)
        if state['serial']!='PRPGJ2494' or not state.get('parked'):
            raise RuntimeError('Expected real instrument parked')
        current=h.call('GET','calibration/export',binary=True)
        # Export zip timestamps vary; the analysis remains bound to its saved
        # camera matrices. Fresh captures are checked for image registration.
        (folder/'frame_check_calibration_export.zip').write_bytes(current)
    records=[]
    for site,native_id in SITES.items():
        for z in (0,20):
            name=f'registration_site{site}_z{z}.png';path=folder/name
            if args.capture:
                path.write_bytes(h.call('GET',f'camera/position/{site}/15/{z}',binary=True))
            crop=cv2.imread(str(path),0)
            registration=register_crop(crop,raw,calibration)
            center=np.array([[[(crop.shape[1]-1)/2,(crop.shape[0]-1)/2]]],float)
            pixel=cv2.perspectiveTransform(center,registration['homography']).reshape(2)
            camera_point=intersect_pixel(pixel,z,calibration,registration['camera_matrix'])
            s=native[native_id]
            native_point=[s['left_bottom_front_x']+s['length']/2,
                          s['left_bottom_front_y']+s['width']/2,s['left_bottom_front_z']+z]
            records.append(dict(site=site,requested_height_mm=z,camera_point=camera_point.tolist(),
                                native_point=native_point,held_out=site in (2,5),
                                registration_inliers=registration['inliers'],
                                registration_rms_pixels=registration['rms_pixels'],
                                image_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            print(json.dumps(records[-1]),flush=True)
    fit=[v for v in records if not v['held_out']];check=[v for v in records if v['held_out']]
    report=dict(kind='vendor_camera_native_frame_crosscheck',serial='PRPGJ2494',
                checked_at=datetime.now(timezone.utc).isoformat(),motion_sent=False,
                physical_validation_complete=False,reference_kind='vendor API site centers; not independent physical measurements',
                records=records,calibration_sha256=calibration_hash)
    try:
        result=fit_registration([v['camera_point'] for v in fit],[v['native_point'] for v in fit],
                                [v['camera_point'] for v in check],[v['native_point'] for v in check],
                                serial='PRPGJ2494',calibration_sha256=calibration_hash,
                                evidence='Six vendor site centers at two heights; native geometry read-only evidence')
        report.update(frame_fit=result,passed=True)
    except ValueError as e:
        report.update(passed=False,error=str(e))
    (folder/'camera_native_frame_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))

if __name__=='__main__': main()
