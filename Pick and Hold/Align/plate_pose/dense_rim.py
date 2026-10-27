"""Independent dense rim flow against the original image; camera geometry only."""
import cv2
import numpy as np
from live_projection import Tracker
from project_taught_disks import transform
from vision import DetectionError


class DenseRim:
    def __init__(self,reference,corners,outlines):
        self.base=Tracker(reference,corners,outlines,mode='rim')
        self.size=self.base.size
        mask=np.zeros(self.base.reference_gray.shape,np.uint8)
        cv2.fillConvexPoly(mask,np.rint(self.base.corners).astype(np.int32),255)
        mask=cv2.erode(mask,np.ones((17,17),np.uint8))
        d=cv2.distanceTransform(mask,cv2.DIST_L2,5)
        mask=np.uint8((d>0)&(d<35))*255
        points=cv2.goodFeaturesToTrack(self.base.reference_gray,600,.01,5,mask=mask,blockSize=5)
        if points is None or len(points)<50:raise DetectionError('Insufficient original dense rim texture.')
        self.points=points.astype(np.float32)

    def track(self,image,seed):
        gray=self.base.feature_gray(image)
        rectified=cv2.warpPerspective(gray,np.linalg.inv(seed),self.size)
        settings=dict(winSize=(31,31),maxLevel=1,
            criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.001),flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
        forward,status,_=cv2.calcOpticalFlowPyrLK(self.base.reference_gray,rectified,self.points,self.points.copy(),**settings)
        if forward is None:raise DetectionError('Dense forward tracking unavailable.')
        backward,back_status,_=cv2.calcOpticalFlowPyrLK(rectified,self.base.reference_gray,forward,self.points.copy(),**settings)
        if backward is None:raise DetectionError('Dense reverse tracking unavailable.')
        valid=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(backward[:,0]-self.points[:,0],axis=1)<.5)&(np.linalg.norm(forward[:,0]-self.points[:,0],axis=1)<3)
        source=self.points[valid,0];target=forward[valid,0]
        if len(source)<50:raise DetectionError(f'Only {len(source)}/{len(self.points)} dense rim tracks survive.')
        cv2.setRNGSeed(0)
        delta,inside=cv2.findHomography(source,target,cv2.RANSAC,1.5,maxIters=3000,confidence=.999)
        if delta is None:raise DetectionError('No dense rim transform.')
        inside=inside.ravel().astype(bool)
        fraction=float(inside.sum()/len(self.points))
        error=np.linalg.norm(transform(source[inside],delta)-target[inside],axis=1)
        rms=float(np.sqrt(np.mean(error**2)))
        coverage=cv2.contourArea(cv2.convexHull(source[inside]))/cv2.contourArea(self.base.corners)
        if fraction<.65 or inside.sum()<50 or rms>.8 or error.max()>2 or coverage<.5:
            raise DetectionError(f'Dense rim rejected: {inside.sum()}/{len(self.points)} ({fraction:.1%}), RMS {rms:.3f}, coverage {coverage:.3f}.')
        h=seed@delta
        return dict(H=h,inliers=int(inside.sum()),matches=len(self.points),agreement=fraction,rms_px=rms,coverage=float(coverage),
                    corners=transform(self.base.corners,h),motion_authorized=False)
