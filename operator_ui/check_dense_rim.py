"""Offline check of dense original-reference rim geometry; no robot access."""
from check_multiview_rim import ROOT,commissioned_tracker,cv2,json,DetectionError
import numpy as np
from dense_rim import DenseRim
from project_taught_disks import transform
r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
ref=cv2.imread(r['images']['target']['path']);outlines={c['label']:c['pixels'] for c in r['virtual_circles']}
t=commissioned_tracker(ROOT,r,ref);dense=DenseRim(ref,r['corners_native_px']['target'],outlines)
files=list((ROOT/'operator_ui/reports/projected_disk_pilot/wider_view_validation_20261026').glob('fresh_*.jpg'))
files+=list((ROOT/'operator_ui/reports/projected_disk_pilot/multiview_spaced_validation_20261026').glob('fresh_*.jpg'))
for path in files:
    image=cv2.imread(str(path));seeds=[]
    for name,tracker,h0,anchor_rms in t.views:
        try:
            a=tracker.track(image)
            seeds.append((a['registration_rmse_px']+(anchor_rms or 0),name,np.array(a['H_preview_from_reference_preview'])@h0))
        except DetectionError:pass
    if not seeds:print(json.dumps(dict(image=path.name,ok=False,error='no seed')));continue
    _,name,h=min(seeds,key=lambda v:v[0])
    try:
        result=dense.track(image,h)
        points=np.vstack(list(dense.base.outlines.values()))
        spread=float(np.linalg.norm(transform(points,h)-transform(points,result['H']),axis=1).max())
        print(json.dumps(dict(image=str(path.relative_to(ROOT)),ok=True,seed=name,disk_spread=spread,
                             **{k:v for k,v in result.items() if k not in ('H','corners')})),flush=True)
    except DetectionError as e:print(json.dumps(dict(image=str(path.relative_to(ROOT)),ok=False,error=str(e))),flush=True)
