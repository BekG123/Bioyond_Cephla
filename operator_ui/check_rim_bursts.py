"""Offline median-burst experiment on stationary, unique camera frames."""
from check_multiview_rim import ROOT,commissioned_tracker,cv2,json,DetectionError
import numpy as np
r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
t=commissioned_tracker(ROOT,r,cv2.imread(r['images']['target']['path']))
folder=ROOT/'operator_ui/reports/projected_disk_pilot/multiview_spaced_validation_20261026'
images=[cv2.imread(str(folder/f'fresh_{n}.jpg')) for n in range(1,11)]
for start in range(6):
    image=np.median(np.stack(images[start:start+5]),axis=0).astype(np.uint8)
    try:
        a=t.track(image)
        print(json.dumps(dict(start=start+1,ok=True,disk_spread=a['disk_view_spread_px'],views=a['supporting_views'])))
    except DetectionError as e:print(json.dumps(dict(start=start+1,ok=False,error=str(e))))
