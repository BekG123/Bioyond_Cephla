"""Read-only Cellvis commissioning measurements. Never dispatches motion.

Projects the measured original printed disks onto an explicitly seeded plate
rim. Uses vendor Wide XY/yaw math; virtual radii never estimate depth. This
does not confer grip acceptance or replace the commissioned 48-well tracker.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen
from uuid import uuid4

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Pick and Hold/Align/plate_pose'), str(ROOT/'bioyond-s4-mcp')]
from rim_edges import rim_edges
from grid_preview import detect
from project_taught_disks import transform
from projected_plate_calibration import measurement_from_outlines
import teach


def measure(image, seed, reference, pose, cfg, *, rim_sample_span=(.12,.88),rim_tangent_radius=0):
    if image.shape[:2] != (2048,3072):
        raise ValueError('Camera resolution changed.')
    # Blurred Cellvis top-row rings fell just below the generic Hough vote
    # threshold. Extract more candidates, retaining the same independent
    # grid coverage, geometric residual and 20/24 measured-well requirements.
    grid = detect(image,4,6,candidate_votes=24)
    corners, edges = rim_edges(cv2.resize(image,(1200,800)),seed,
                              polarities=[-1]*4,half_width=14,sample_span=rim_sample_span,tangent_radius=rim_tangent_radius)
    if np.any(corners < 3) or np.any(corners > [1197,797]):
        raise ValueError('Measured rim is clipped.')
    h = cv2.getPerspectiveTransform(np.array([[0,0],[1,0],[1,1],[0,1]],np.float32),corners*2.56)
    outlines = {}
    for c in reference['virtual_circles']:
        a=transform(c['normalized_plate_outline'],h)
        outlines[c['label']]=a.tolist()
    measured=measurement_from_outlines(outlines,pose,cfg)
    return dict(measured,corners_preview_px=corners.tolist(),edges=edges,
        measured_wells=len(grid['points']),grid_rmse_px=grid['rmse'],
        grid_detector='cellvis24-hough24-grid-v2',grid_candidate_count=grid['candidate_count'],
        projected_original_disks_px=outlines,
        motion_authorized=False,orientation_assumption='Large left / small right; A1 unresolved')


def summarize(measurements):
    if len(measurements)!=3:raise ValueError('Three independent bursts required.')
    xy=np.array([m['error_xy_mm'] for m in measurements])
    target_xy=np.array([[m['target']['x'],m['target']['y']] for m in measurements])
    corners=np.array([m['corners_preview_px'] for m in measurements])
    yaw=np.array([m['target']['rz'] for m in measurements])
    xy_spread=float(np.linalg.norm(xy[:,None]-xy[None,:],axis=2).max())
    target_spread=float(np.linalg.norm(target_xy[:,None]-target_xy[None,:],axis=2).max())
    corner_spread=float(np.linalg.norm(corners[:,None]-corners[None,:],axis=3).max())
    yaw_spread=float(np.abs((yaw[:,None]-yaw[None,:]+180)%360-180).max())
    return dict(stationary_checks_passed=xy_spread<=.25 and target_spread<=.25 and corner_spread<=.8 and yaw_spread<=.2,
                xy_spread_mm=xy_spread,target_xy_spread_mm=target_spread,corner_spread_preview_px=corner_spread,yaw_spread_deg=yaw_spread,
                motion_authorized=False,full_calibration_complete=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    folder=args.output/('observation_'+uuid4().hex[:12]);folder.mkdir(parents=True)
    source=ROOT/'operator_ui/reports/plate_projection_taught_48/result.json'
    reference=json.loads(source.read_bytes());seed=json.loads(args.seed.read_bytes())['fitted']
    cfg=next(c for c in teach._configs() if c['name']=='Wide')
    ok,_=teach.selftest()
    if not ok:raise RuntimeError('Vendor math selftest failed.')
    record=dict(status='measuring',motion_sent=False,bursts=[],source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),seed_path=str(args.seed.resolve()),seed_sha256=hashlib.sha256(args.seed.read_bytes()).hexdigest())
    def save(): (folder/'run.json').write_text(json.dumps(record,indent=2))
    def state():
        with urlopen('http://127.0.0.1:5002/state',timeout=15) as r:s=json.load(r)
        robot=s['robot']
        if not robot.get('connected') or robot.get('errors') or s['sequence'].get('active'):
            raise RuntimeError('Stationary connected fault-free arm required; no reconnect or retry.')
        return s
    try:
        before=state();pose=before['robot']['pose_mm'];record['before']=before;save()
        if abs(pose['Z']-289.129)>.1 or abs(pose['Rz']+3.88)>.05:
            raise ValueError('Use the reviewed observation height and wrist angle.')
        for i in range(3):
            frames=[];hashes=[]
            for j in range(5):
                time.sleep(.65)
                with urlopen('http://127.0.0.1:5002/frame',timeout=15) as r:data=r.read();error=r.headers.get('X-Error','')
                if error:raise RuntimeError(error)
                s=state()
                if s['camera']['age_s']>1 or any(abs(s['robot']['pose_mm'][k]-pose[k])>.05 for k in ('X','Y','Z','Rz')):
                    raise RuntimeError('Camera stale or arm moved during observation.')
                frames.append(cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR))
                hashes.append(hashlib.sha256(data).hexdigest());(folder/f'burst_{i}_{j}.jpg').write_bytes(data)
            if len(set(hashes))<3:raise ValueError('Insufficient distinct camera frames.')
            median=np.median(frames,axis=0).astype(np.uint8);cv2.imwrite(str(folder/f'median_{i}.png'),median)
            measurement=measure(median,seed,reference,pose,cfg)
            record['bursts'].append(dict(hashes=hashes,measurement=measurement));save()
            print(json.dumps({k:measurement[k] for k in ('target','error_xy_mm','measured_wells')}),flush=True)
        record.update(status='measured',summary=summarize([b['measurement'] for b in record['bursts']]))
        print(json.dumps(record['summary']),flush=True)
    except Exception as error:
        record.update(status='rejected',error=str(error));raise
    finally:
        save();print(str(folder/'run.json'),flush=True)


if __name__=='__main__':main()
