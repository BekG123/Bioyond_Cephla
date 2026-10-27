"""Offline test of using a verified previous transform only as initialization."""
from check_multiview_rim import ROOT, cv2, json, DetectionError
from grid_pattern import commissioned_grid_tracker
import numpy as np
from project_taught_disks import transform

r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
t=commissioned_grid_tracker(ROOT,r,cv2.imread(r['images']['target']['path']))
events=[json.loads(line) for line in (ROOT/'operator_ui/reports/projected_disk_pilot/20261026_223134_3938ef5b.jsonl').read_text().splitlines()]
previous=None
for event in events:
    if event['event']!='stationary_image_burst':continue
    frame=cv2.imread(event['median_image'])
    try:
        if previous is None:
            result=t.track(frame)
            previous=np.asarray(result['H_preview_from_reference_preview'])@np.linalg.inv(np.asarray(t.registration['H_preview_from_reference_preview']))
        else:
            result=t.anchor.track(frame,seed=previous)
            landmarks=np.vstack([t.original.corners,*t.original.outlines.values()])
            alternatives=[transform(landmarks,np.array(b)@np.array(a)) for b in result['group_homographies'] for a in t.registration['group_homographies']]
            errors=np.array([np.linalg.norm(a-b,axis=1) for a in alternatives for b in alternatives])
            if errors[:,4:].max()>.8 or errors.max()>2:raise DetectionError('Composed group disagreement')
            previous=np.asarray(result['H_preview_from_reference_preview'])
        print(json.dumps(dict(image=event['median_image'],ok=True,wells=result['supported_wells'])),flush=True)
    except DetectionError as ex:print(json.dumps(dict(image=event['median_image'],ok=False,error=str(ex))),flush=True)
