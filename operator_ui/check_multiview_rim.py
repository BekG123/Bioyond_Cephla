"""Offline frozen-view replay. Never commands the arm."""
import json
import argparse
import hashlib
import time
from urllib.request import urlopen
from pathlib import Path
import sys
import cv2
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'Pick and Hold/Align/plate_pose'))
from multiview_rim import commissioned_tracker
from vision import DetectionError

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fresh',type=int,default=0)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
    t=commissioned_tracker(ROOT,r,cv2.imread(r['images']['target']['path']))
    folders=ROOT/'operator_ui/reports/projected_disk_pilot'
    files=[folders/'rectified_rim_20261026_verified/after_retry_raw.jpg',folders/'after_rim_fix_20261026/raw.jpg']
    files += list((folders/'rim_refinement_20261026').glob('validation_*.jpg'))
    files += list((folders/'strict_matches_validation').glob('validation_*.jpg'))
    observations=[]
    if args.fresh:
        if not args.output:raise RuntimeError('--output required for fresh evidence')
        if args.output.exists() and any(args.output.iterdir()):raise RuntimeError('Preserving existing validation evidence.')
        args.output.mkdir(parents=True,exist_ok=True)
        def read(endpoint):
            with urlopen('http://127.0.0.1:5002'+endpoint,timeout=6) as response:
                if response.headers.get('X-Error'):raise RuntimeError(response.headers['X-Error'])
                return response.read()
        origin=None
        for n in range(args.fresh):
            before=json.loads(read('/state'));raw=read('/frame');after=json.loads(read('/state'))
            for s in (before,after):
                if not s['robot'].get('connected') or not s['robot'].get('ok') or s['sequence']['active']:
                    raise RuntimeError('Require idle connected healthy robot for stationary evidence.')
                pose=s['robot']['pose_mm'];origin=origin or pose
                if any(abs(pose[k]-origin[k])>.1 for k in ('X','Y','Z','Rz')):raise RuntimeError('Robot moved during capture')
            if after['camera'].get('age_s',999)>.8:raise RuntimeError('Stale camera')
            path=args.output/f'fresh_{n+1}.jpg';path.write_bytes(raw);files.append(path)
            observations.append(dict(image=str(path),before=before,after=after))
            time.sleep(1.)
    rows=[]
    for path in files:
        try:
            result=t.track(cv2.imread(str(path)))
            row=dict(image=str(path),ok=True,spread=result['view_spread_px'],disk_spread=result['disk_view_spread_px'],views=result['supporting_views'])
        except DetectionError as error:row=dict(image=str(path),ok=False,error=str(error))
        row['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();rows.append(row)
        print(json.dumps(row),flush=True)
    if args.output:
        (args.output/'result.json').write_text(json.dumps(dict(motion_started=False,observations=observations,results=rows),indent=2))
    if not all(r['ok'] for r in rows):sys.exit(1)
