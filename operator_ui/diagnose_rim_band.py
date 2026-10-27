"""Compare rim-band definitions offline; no hardware commands."""
import json
from pathlib import Path
import sys
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'Pick and Hold/Align/plate_pose'))
from live_projection import Tracker
from vision import DetectionError

if __name__=='__main__':
    r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
    reference=cv2.imread(r['images']['target']['path'])
    frame=cv2.imread(str(ROOT/'operator_ui/reports/projected_disk_pilot/rectified_rim_20261026_verified/after_retry_raw.jpg'))
    for erosion in (1,5,9,17):
        for width in (20,35,50):
            t=Tracker(reference,r['corners_native_px']['target'],{c['label']:c['pixels'] for c in r['virtual_circles']},mode='rim')
            mask=np.zeros(t.reference_gray.shape,np.uint8)
            cv2.fillConvexPoly(mask,np.rint(t.corners).astype(np.int32),255)
            mask=cv2.erode(mask,np.ones((erosion,erosion),np.uint8))
            distance=cv2.distanceTransform(mask,cv2.DIST_L2,5)
            mask=np.uint8((distance>0)&(distance<width))*255
            t.keys,t.desc=t.sift.detectAndCompute(t.reference_gray,mask)
            row=dict(erosion=erosion,width=width,reference_features=len(t.keys))
            try:
                result=t.track(frame)
                row.update({k:result[k] for k in ('inliers','matches','inlier_fraction','registration_rmse_px','coverage_fraction','corners_px')})
            except DetectionError as e:row['error']=str(e)
            print(json.dumps(row),flush=True)
