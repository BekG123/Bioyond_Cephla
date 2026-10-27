"""Offline rim measurement and inspection overlays; no motion access."""
from check_multiview_rim import ROOT,commissioned_tracker,cv2,json,DetectionError
import numpy as np
from rim_edges import rim_edges
from project_taught_disks import transform
r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
reference=cv2.imread(r['images']['target']['path']);t=commissioned_tracker(ROOT,r,reference)
paths=[None,ROOT/'operator_ui/reports/projected_disk_pilot/wider_view_validation_20261026/fresh_1.jpg']
folder=ROOT/'operator_ui/reports/projected_disk_pilot/rim_edges_20261026'
folder.mkdir(exist_ok=True)
for path in paths:
    image=reference if path is None else cv2.imread(str(path))
    if path is None:q=t.original.corners
    else:
        candidates=[]
        for name,tracker,h0,_ in t.views:
            try:
                result=tracker.track(image)
                candidates.append((result['registration_rmse_px'],np.array(result['H_preview_from_reference_preview'])@h0))
            except DetectionError:pass
        if not candidates:raise RuntimeError('No provisional visual seed')
        _,h=min(candidates,key=lambda x:x[0]);q=transform(reference_fitted,h)
    small=cv2.resize(image,t.size)
    try:
        fitted,edges=rim_edges(small,q,polarities=None if path is None else reference_polarities,half_width=14. if path is None else 6.)
        if path is None:
            reference_fitted=fitted;reference_polarities=[e['polarity'] for e in edges]
        print(json.dumps(dict(image=str(path),ok=True,corners=fitted.tolist(),edges=[{k:v for k,v in e.items() if k!='points'} for e in edges])),flush=True)
        cv2.polylines(small,[np.rint(q).astype(np.int32)],True,(0,0,255),2)
        cv2.polylines(small,[np.rint(fitted).astype(np.int32)],True,(0,255,0),2)
        for e in edges:
            for p in e['points']:cv2.circle(small,tuple(np.rint(p).astype(int)),1,(255,180,0),-1)
    except DetectionError as e:print(json.dumps(dict(image=str(path),ok=False,error=str(e))),flush=True)
    cv2.imwrite(str(folder/('reference.jpg' if path is None else 'current.jpg')),small)
