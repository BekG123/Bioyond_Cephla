"""Frozen, original-anchored rim views. No online reference updates or motion."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from live_projection import Tracker
from project_taught_disks import transform,quadrilateral
from vision import DetectionError


class MultiViewRim:
    def __init__(self,reference,corners,outlines,anchors):
        self.original=Tracker(reference,corners,outlines,mode='rim')
        self.size=self.original.size
        self.views=[('original',self.original,np.eye(3),None)]
        for name,image in anchors:
            registered=self.original.track(image)
            h=np.asarray(registered['H_preview_from_reference_preview'])
            scale=self.original.scale
            tracker=Tracker(image,np.asarray(registered['corners_px'])/scale,
                {c['label']:np.asarray(c['pixels'])/scale for c in registered['virtual_circles']},mode='rim')
            self.views.append((name,tracker,h,registered['registration_rmse_px']))
        if len(self.views)<3:raise DetectionError('Two frozen nearby reference views are required.')

    def track(self,image):
        accepted=[];rejected={}
        landmarks=np.vstack([self.original.corners,*self.original.outlines.values()])
        for name,tracker,anchor_h,anchor_rms in self.views:
            try:
                result=tracker.track(image)
                h=np.asarray(result['H_preview_from_reference_preview'])@anchor_h
                points=transform(landmarks,h)
                q=quadrilateral(points[:4])
                # Preserve original-reference clipping and local geometry gates.
                area=cv2.contourArea(q)/cv2.contourArea(self.original.corners)
                angle=np.degrees(np.arctan2(*(q[1]-q[0])[::-1])-np.arctan2(*(self.original.corners[1]-self.original.corners[0])[::-1]))
                if not .65<area<1.5 or abs(angle)>30:raise DetectionError('Composed plate geometry outside local range.')
                if np.any(q<3) or np.any(q[:,0]>self.size[0]-3) or np.any(q[:,1]>self.size[1]-3):
                    raise DetectionError('Composed plate is clipped.')
                accepted.append((name,result,h,points,anchor_rms))
            except DetectionError as error:rejected[name]=str(error)
        if len(accepted)<2:
            raise DetectionError('Fewer than two frozen views agree: '+json.dumps(rejected))
        spread=max(float(np.linalg.norm(a[3]-b[3],axis=1).max()) for a in accepted for b in accepted)
        disk_spread=max(float(np.linalg.norm(a[3][4:]-b[3][4:],axis=1).max()) for a in accepted for b in accepted)
        # Calibration uses these virtual landmarks. Require subpixel agreement
        # across their entire outlines, plus the existing 2 px point-error scale
        # at the outer corners, where a homography extrapolates most strongly.
        if disk_spread>.8 or spread>2.:
            raise DetectionError(f'Frozen rim views disagree: outlines {disk_spread:.3f}/0.8 px, full extent {spread:.3f}/2.0 px.')
        # Choose one measured transform; never average away a failed view.
        name,result,h,_,_=min(accepted,key=lambda a:a[1]['registration_rmse_px']+(a[4] or 0.))
        result=dict(result)
        result.update(H_preview_from_reference_preview=h.tolist(),corners_px=transform(self.original.corners,h).tolist(),
            virtual_circles=[dict(label=k,pixels=transform(v,h).tolist()) for k,v in self.original.outlines.items()],
            tracking_mode='frozen_multiview_rim',selected_view=name,view_spread_px=spread,disk_view_spread_px=disk_spread,
            supporting_views=[dict(name=a[0],agreement=a[1]['inlier_fraction'],inliers=a[1]['inliers'],
                matches=a[1]['matches'],rms_px=a[1]['registration_rmse_px'],anchor_rms_px=a[4]) for a in accepted],
            rejected_views=rejected,reference_updates=0)
        return result


def commissioned_tracker(root,report,reference):
    """Load two pose-separated, hash-checked stationary camera evidence sets."""
    root=Path(root)
    expected=hashlib.sha256((root/'operator_ui/reports/plate_projection_taught_48/result.json').read_bytes()).hexdigest()
    folders=('rim_refinement_20261026','rectified_rim_20261026_verified')
    anchors=[];poses=[]
    for folder in folders:
        evidence=json.loads((root/'operator_ui/reports/projected_disk_pilot'/folder/'comparison.json').read_text())
        if evidence['reference_sha256']!=expected:raise DetectionError('Frozen view references a different plate mapping.')
        start,end=evidence['initial_pose'],evidence['final_pose']
        if not start or not end or any(abs(start[k]-end[k])>.1 for k in ('X','Y','Z','Rz')):
            raise DetectionError('Frozen view has no stationary robot evidence.')
        poses.append(start)
        images=[]
        for item in (r for r in evidence['results'] if r['kind']=='heldout_fresh'):
            path=(root/item['image']).resolve()
            if not path.is_relative_to(root.resolve()):raise DetectionError('Reference image outside project.')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise DetectionError('Frozen view image changed.')
            images.append(cv2.imread(str(path)))
        if len(images)!=5:raise DetectionError('Frozen view requires five stationary samples.')
        anchors.append((folder,np.median(np.stack(images),axis=0).astype(np.uint8)))
    if np.hypot(poses[0]['X']-poses[1]['X'],poses[0]['Y']-poses[1]['Y'])<2:
        raise DetectionError('Frozen views are not separated viewpoints.')
    return MultiViewRim(reference,report['corners_native_px']['target'],
        {c['label']:c['pixels'] for c in report['virtual_circles']},anchors)
