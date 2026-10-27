"""Map annotated original disk contours into a measured reference plate plane."""
import cv2
import numpy as np
from vision import DetectionError, finite_array


def map_reference(corners_undistorted_px,corners_plate_mm,contours_undistorted_px):
    """Use ordered coplanar corners and sampled outlines, NOT pixel circle radii.

    This is an annotation utility, not automatic disk/reference calibration.
    All input pixels must already use the same undistorted camera image.
    """
    pixels=finite_array(corners_undistorted_px,(4,2),'reference corners')
    plane=finite_array(corners_plate_mm,(4,2),'measured plate corners')
    for poly in (pixels,plane):
        if not cv2.isContourConvex(poly.astype(np.float32)) or abs(cv2.contourArea(poly.astype(np.float32)))<1:
            raise DetectionError('Ordered nondegenerate reference quadrilateral required')
    h=cv2.getPerspectiveTransform(pixels.astype(np.float32),plane.astype(np.float32))
    circles=[]
    if set(contours_undistorted_px)!= {'large','small'}:
        raise DetectionError('Both large and small disk outlines required')
    for label,outline in contours_undistorted_px.items():
        points=np.asarray(outline,dtype=float)
        if points.ndim!=2 or points.shape[1]!=2 or len(points)<12 or not np.isfinite(points).all():
            raise DetectionError('At least 12 finite outline samples required per disk')
        xy=cv2.perspectiveTransform(points.reshape(-1,1,2),h).reshape(-1,2)
        matrix=np.column_stack([2*xy,np.ones(len(xy))]);rhs=np.sum(xy**2,axis=1)
        fit,_,rank,_=np.linalg.lstsq(matrix,rhs,rcond=None)
        radius_sq=fit[2]+fit[0]**2+fit[1]**2
        if rank!=3 or radius_sq<=0: raise DetectionError('Degenerate disk outline')
        radius=float(np.sqrt(radius_sq))
        residual=float(np.sqrt(np.mean((np.linalg.norm(xy-fit[:2],axis=1)-radius)**2)))
        if residual>.2: raise DetectionError('Disk outline is inconsistent with reference plane (>0.2 mm RMS)')
        circles.append(dict(label=label,center_mm=fit[:2].tolist(),radius_mm=radius,fit_rmse_mm=residual))
    by_label={c['label']:c for c in circles}
    if by_label['large']['radius_mm']<=by_label['small']['radius_mm']:
        raise DetectionError('Large/small labels are reversed or ambiguous')
    return dict(offline_only=True,motion_authorized=False,virtual_circles=circles,
        note='Reference plate frame; mapping into a different plate/grasp frame still requires a measured rigid relationship.')
