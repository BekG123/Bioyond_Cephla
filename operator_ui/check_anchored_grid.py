"""Offline fixed-height anchor experiment; no motion or production writes."""
from check_multiview_rim import ROOT,cv2,json,DetectionError
from grid_pattern import GridPatternTracker
from project_taught_disks import transform
import numpy as np
r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
ref=cv2.imread(r['images']['target']['path'])
original=GridPatternTracker(ref,r['corners_native_px']['target'],{c['label']:c['pixels'] for c in r['virtual_circles']})
base=ROOT/'operator_ui/reports/projected_disk_pilot'
files=sorted((base/'wider_view_validation_20261026').glob('fresh_*.jpg'))
anchor=np.median([cv2.imread(str(p)) for p in files],axis=0).astype(np.uint8)
registered=original.track(anchor)
print(json.dumps(dict(anchor_wells=registered['supported_wells'],anchor_spread=registered['disk_group_spread_px'])))
scale=anchor.shape[1]/1200
tracker=GridPatternTracker(anchor,np.array(registered['corners_px'])*scale,
    {c['label']:np.array(c['pixels'])*scale for c in registered['virtual_circles']})
first=None
for path in sorted((base/'grid_pattern_after_move_20261026').glob('fresh_*.jpg')):
    try:
        a=tracker.track(cv2.imread(str(path)))
        points=np.vstack([c['pixels'] for c in a['virtual_circles']])
        if first is None:first=points
        print(json.dumps(dict(image=path.name,ok=True,wells=a['supported_wells'],correlations=a['pattern_correlations'],
            spread=a['disk_group_spread_px'],stationary_shift=float(np.linalg.norm(points-first,axis=1).max()),
            H=(np.array(a['H_preview_from_reference_preview'])@np.array(registered['H_preview_from_reference_preview'])).tolist())),flush=True)
    except DetectionError as e:print(json.dumps(dict(image=path.name,ok=False,error=str(e))),flush=True)
