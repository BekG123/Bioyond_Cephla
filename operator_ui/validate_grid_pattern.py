"""Offline fixed-parameter grid-pattern tests on saved evidence; no hardware."""
import argparse
from pathlib import Path
from check_multiview_rim import ROOT, cv2, json, DetectionError
from grid_pattern import GridPatternTracker,commissioned_grid_tracker
from project_taught_disks import transform
import numpy as np

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--anchored',action='store_true')
    args=parser.parse_args()
    r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
    ref=cv2.imread(r['images']['target']['path'])
    t=commissioned_grid_tracker(ROOT,r,ref) if args.anchored else GridPatternTracker(ref,r['corners_native_px']['target'],{c['label']:c['pixels'] for c in r['virtual_circles']})
    base=ROOT/'operator_ui/reports/projected_disk_pilot'
    rows=[];groups={};last_overlay=None
    for folder in ('wider_view_validation_20261026','wider_view_followup_20261026','multiview_spaced_validation_20261026','grid_pattern_after_move_20261026'):
        for path in sorted((base/folder).glob('fresh_*.jpg')):
            row=dict(image=str(path.relative_to(ROOT)))
            try:
                image=cv2.imread(str(path));a=t.track(image)
                points=np.vstack([c['pixels'] for c in a['virtual_circles']])
                baseline=groups.setdefault(folder,points)
                row.update(ok=True,stationary_disk_shift_px=float(np.linalg.norm(points-baseline,axis=1).max()),result=a)
                last_overlay=cv2.resize(image,t.size)
                for c in a['virtual_circles']:
                    cv2.polylines(last_overlay,[np.rint(c['pixels']).astype(np.int32)],True,(0,190,255),2)
            except DetectionError as e:row.update(ok=False,error=str(e))
            rows.append(row)
            print(json.dumps({k:v for k,v in row.items() if k!='result'}|({k:a[k] for k in ('supported_wells','disk_group_spread_px','pattern_correlations')} if row['ok'] else {})),flush=True)
    if args.output:
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'result.json').write_text(json.dumps(dict(offline_only=True,motion_started=False,results=rows),indent=2))
        if last_overlay is not None:cv2.imwrite(str(args.output/'overlay.jpg'),last_overlay)
