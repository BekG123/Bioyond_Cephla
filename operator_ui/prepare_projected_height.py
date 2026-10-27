"""Read-only preparation of a transferred plate observation-height reference.

No controller mutations, motion, auto preparation, target publishing or depth
estimation from virtual disks. The support-height assumption needs an operator
answer before this candidate can be used for a physical trial.
"""
import hashlib
import json
import time
from pathlib import Path
from urllib.request import urlopen
import cv2
import numpy as np
from projected_disk_trial import ROOT, Perception, same_pose
from autonomy import check_path, TransferError

SOURCE=ROOT/'operator_ui/reports/calibration/20261024_211431_04c13f94.jsonl'
MODEL=ROOT/'Pick and Hold/Align/plate_pose/plate_48_pending.json'
OUTPUT=ROOT/'operator_ui/reports/projected_disk_pilot/height_reference_preview_20261026.json'

def read(endpoint):
    with urlopen('http://127.0.0.1:5002'+endpoint,timeout=8) as response:
        if response.headers.get('X-Error'):raise TransferError(response.headers['X-Error'])
        return response.read()

def state():
    s=json.loads(read('/state'));r=s['robot']
    if (s['sequence']['active'] or not r.get('connected') or not r.get('ok')
            or r.get('errors')):raise TransferError('Require healthy stationary robot feedback.')
    return s

def main():
    records=[json.loads(s) for s in SOURCE.read_text().splitlines()]
    done=records[-1]
    result=done.get('result',{})
    if (done.get('event')!='completed' or not result.get('ok')
            or result['target'].get('converged') is not True
            or result['target'].get('config')!='Wide'):
        raise TransferError('Source is not a completed Wide calibration.')
    heights=json.loads(MODEL.read_text())['height_reference']
    delta=heights['well_plate_height_mm']-heights['original_two_disk_plate_height_mm']
    target_z=result['calibration_pose']['Z']+delta
    before=state();pose=before['robot']['pose_mm']
    images=[];hashes=[]
    for _ in range(5):
        raw=read('/frame');hashes.append(hashlib.sha256(raw).hexdigest())
        images.append(cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR))
        if not same_pose(pose,state()['robot']['pose_mm']):raise TransferError('Pose changed during preview.')
        time.sleep(1.)
    if len(set(hashes))<3:raise TransferError('Not enough distinct fresh images.')
    perception=Perception('anchored_grid',5)
    measurement=perception.measure(np.median(images,axis=0).astype(np.uint8),pose)
    if not same_pose(pose,state()['robot']['pose_mm']):raise TransferError('Pose changed during solving.')
    cfg=json.loads((ROOT/'operator_ui/robot_params.json').read_text())
    envelope={k:(before['envelope'][k]['min'],before['envelope'][k]['max']) for k in ('X','Y','Z')}
    full={**pose,'Z':target_z}
    first={**pose,'Z':pose['Z']+min(2.,max(-2.,target_z-pose['Z']))}
    checked=check_path(pose,full,before['robot']['joints'],cfg,envelope)
    check_path(pose,first,before['robot']['joints'],cfg,envelope)
    report=dict(timestamp=time.time(),preview_only=True,motion_started=False,
        execution_authorized=False,same_support_height_confirmed=False,
        source_log=str(SOURCE),source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        source_calibration_pose=result['calibration_pose'],height_reference=heights,
        height_reference_sha256=hashlib.sha256(MODEL.read_bytes()).hexdigest(),
        method='Transfer a successful observation Z by the measured physical top-surface height difference; requires unchanged bottom support.',
        start=pose,candidate_target=full,candidate_first_step=first,speed=5,
        checked_final_joints=checked,frame_hashes=hashes,
        current_error_xy_mm=measurement['error_xy_mm'],supported_wells=measurement['tracking']['supported_wells'],
        calibration_complete=False,height_calibrated=False,grasp_target_created=False,
        blockers=['Confirm both plate bottoms rest at the same support height.',
                  'Validate changed-height image registration and scale response before multi-step execution.',
                  'This transfers an observation-height reference; it is not an independent absolute depth measurement or grasp height.'])
    OUTPUT.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['preview_only','motion_started','start','candidate_target','candidate_first_step','current_error_xy_mm','supported_wells','blockers']},indent=2))

if __name__=='__main__':main()
