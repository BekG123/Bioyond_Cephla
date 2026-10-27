"""Offline feature-budget comparison on the fixed plate reference."""
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'Pick and Hold/Align/plate_pose'))
from live_projection import Tracker
from vision import DetectionError

def build(count):
    report=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
    tracker=Tracker(cv2.imread(report['images']['target']['path']),report['corners_native_px']['target'],
        {c['label']:c['pixels'] for c in report['virtual_circles']},mode='rim')
    mask=np.zeros(tracker.reference_gray.shape,np.uint8)
    cv2.fillConvexPoly(mask,np.rint(tracker.corners).astype(np.int32),255)
    mask=cv2.erode(mask,np.ones((17,17),np.uint8))
    distance=cv2.distanceTransform(mask,cv2.DIST_L2,5)
    mask=np.uint8((distance>0)&(distance<35))*255
    tracker.sift=cv2.SIFT_create(nfeatures=count,contrastThreshold=.025)
    tracker.keys,tracker.desc=tracker.sift.detectAndCompute(tracker.reference_gray,mask)
    return tracker

if __name__=='__main__':
    frame=cv2.imread(str(ROOT/'operator_ui/reports/projected_disk_pilot/after_rim_fix_20261026/raw.jpg'))
    original_flow=cv2.calcOpticalFlowPyrLK
    for window in (21,31,41,51):
        def flow(*args,**kwargs):
            kwargs['winSize']=(window,window)
            return original_flow(*args,**kwargs)
        cv2.calcOpticalFlowPyrLK=flow
        budget=2500
        tracker=build(budget)
        row=dict(window=window,budget=budget,reference_features=len(tracker.keys))
        try:
            result=tracker.track(frame)
            row.update({k:result[k] for k in ('inliers','matches','inlier_fraction','registration_rmse_px','coverage_fraction','corners_px')})
        except DetectionError as error:row['error']=str(error)
        print(json.dumps(row),flush=True)
