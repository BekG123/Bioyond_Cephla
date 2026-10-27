"""Offline well-ring parameter stability; no controller access."""
from check_multiview_rim import ROOT,cv2,json,DetectionError
from grid_preview import fit_grid
import numpy as np
r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
paths=[r['images']['target']['path'],ROOT/'operator_ui/reports/projected_disk_pilot/wider_view_validation_20261026/fresh_1.jpg']
for path in paths:
    image=cv2.imread(str(path));gray=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(1200,800))
    gray=cv2.GaussianBlur(cv2.createCLAHE(2,(8,8)).apply(gray),(5,5),1.2)
    for min_radius,max_radius in ((28,55),(32,46),(36,48)):
        for threshold in (18,22,26,30,34):
            circles=cv2.HoughCircles(gray,cv2.HOUGH_GRADIENT,1.2,75,param1=80,param2=threshold,minRadius=min_radius,maxRadius=max_radius)
            points=[] if circles is None else circles[0,:,:2]
            row=dict(image=str(path),radii=[min_radius,max_radius],threshold=threshold,candidates=len(points))
            try:
                fit=fit_grid(points)
                row.update(ok=True,inliers=len(fit['points']),rms=fit['rmse'],pitch=fit['pitch'],H=fit['h'].tolist())
            except DetectionError as e:row.update(ok=False,error=str(e))
            print(json.dumps(row),flush=True)
