"""Saved-frame plus read-only fresh-camera validation; never sends robot commands."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen
import cv2
import numpy as np
from benchmark_projection_tracking import feature_masks,evaluate,ROOT
from live_projection import Tracker
from vision import DetectionError


def get(path):
    with urlopen('http://127.0.0.1:5002'+path,timeout=6) as response:
        if response.headers.get('X-Error'):raise RuntimeError(response.headers['X-Error'])
        return response.read()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fresh',type=int,default=0)
    parser.add_argument('--output-folder',type=Path)
    args=parser.parse_args()
    baseline_folder=ROOT/'operator_ui/reports/projected_disk_pilot/rim_refinement_20261026'
    folder=(args.output_folder or baseline_folder).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    output=folder/'comparison.json'
    if output.exists():raise RuntimeError('Preserving existing comparison; choose a separate validation run.')
    reference=ROOT/'operator_ui/reports/plate_projection_taught_48/result.json'
    r=json.loads(reference.read_text());source=cv2.imread(r['images']['target']['path'])
    tracker=Tracker(source,r['corners_native_px']['target'],{c['label']:c['pixels'] for c in r['virtual_circles']},mode='rim')
    gray=tracker.gray(source);mask=dict(feature_masks(gray,tracker.corners))['rim_35']
    files=[('development' if n==1 else 'heldout_current',baseline_folder/f'validation_{n}.jpg') for n in range(1,6)]
    files += [('historical',baseline_folder.parent/'strict_matches_validation'/f'validation_{n}.jpg') for n in range(1,6)]
    if args.output_folder:
        files += [('historical',baseline_folder/f'heldout_fresh_{n}.jpg') for n in range(1,6)]
        files += [('development',baseline_folder.parent/'after_rim_fix_20261026/raw.jpg')]
    results=[];poses=[]
    for n in range(args.fresh):
        before=json.loads(get('/state'));raw=get('/frame');after=json.loads(get('/state'))
        if not all(s.get('robot',{}).get('connected') and s['robot'].get('pose_mm') for s in (before,after)):
            raise RuntimeError('Robot disconnected; stationary validation requires pose feedback.')
        poses.extend([before['robot']['pose_mm'],after['robot']['pose_mm']])
        origin=poses[0]
        if any(any(abs(p[k]-origin[k])>.1 for k in ('X','Y','Z','Rz')) for p in poses):
            raise RuntimeError('Arm moved during stationary validation.')
        if after['camera'].get('age_s',999)>.8 or not after['robot'].get('ok'):
            raise RuntimeError('Stale camera or robot feedback.')
        path=folder/f'heldout_fresh_{n+1}.jpg'
        with path.open('xb') as stream:stream.write(raw)
        files.append(('heldout_fresh',path))
        if n+1<args.fresh:time.sleep(.3)
    for kind,path in files:
        frame=cv2.imread(str(path))
        old=evaluate(gray,tracker.gray(frame),mask,tracker.corners,'clahe',True,.6)
        try:
            new=tracker.track(frame)
            new={k:new[k] for k in ('inlier_fraction','inliers','matches','registration_rmse_px','coverage_fraction')}
            new['accepted']=True
        except DetectionError as error:new=dict(accepted=False,reason=str(error))
        results.append(dict(kind=kind,image=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            before={k:old.get(k) for k in ('accepted','inliers','matches','inlier_fraction','rmse_px','coverage')},after=new))
    summary={}
    for group in ('development','heldout_current','historical','heldout_fresh'):
        rows=[r for r in results if r['kind']==group]
        if not rows:continue
        passed=[r['after'] for r in rows if r['after']['accepted']]
        summary[group]=dict(count=len(rows),before_pass=sum(r['before']['accepted'] for r in rows),after_pass=len(passed),
            min_agreement=min((r['inlier_fraction'] for r in passed),default=None),
            max_rms_px=max((r['registration_rmse_px'] for r in passed),default=None))
    record=dict(motion_started=False,comparison_baseline='unrectified LK window21 level3',reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
        tracker_sha256=hashlib.sha256((ROOT/'Pick and Hold/Align/plate_pose/live_projection.py').read_bytes()).hexdigest(),
        unchanged_quality_gates=True,initial_pose=poses[0] if poses else None,
        final_pose=poses[-1] if poses else None,summary=summary,results=results)
    with output.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    print(json.dumps(summary,indent=2))
    if any(s['after_pass']!=s['count'] for s in summary.values()):sys.exit(1)


if __name__=='__main__':main()
