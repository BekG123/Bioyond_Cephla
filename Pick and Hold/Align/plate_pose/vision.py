"""Offline rim/grid detection, metric pose and virtual-circle overlays.

Plate x follows columns, y follows rows, z is normal to the well-rim plane.
Camera axes follow OpenCV. Virtual landmarks never enter the pose estimator.
"""
import math
import cv2
import numpy as np


class DetectionError(ValueError):
    pass


def finite_array(value, shape, name):
    a = np.asarray(value, dtype=np.float64)
    if a.shape != shape or not np.isfinite(a).all():
        raise DetectionError(name+' has invalid shape or nonfinite values')
    return a


def camera_parameters(camera, shape):
    if camera.get('model') != 'opencv_pinhole':
        raise DetectionError('Explicit OpenCV pinhole intrinsics/distortion required; vendor parameters are not interchangeable.')
    if list(camera['image_size_px']) != [shape[1],shape[0]]:
        raise DetectionError('Image resolution differs from calibration; do not silently resize.')
    k = finite_array(camera['K'], (3,3), 'K')
    d = np.asarray(camera['distortion'], dtype=float)
    if d.ndim != 1 or d.size not in (4,5,8,12,14) or not np.isfinite(d).all():
        raise DetectionError('Unsupported distortion coefficients')
    if k[0,0] <= 0 or k[1,1] <= 0 or not np.allclose(k[2],[0,0,1]):
        raise DetectionError('Invalid intrinsic matrix')
    return k,d


def model_points(model):
    w,h = float(model['feature_width_mm']),float(model['feature_height_mm'])
    grid = model['grid']
    rows,cols = grid['rows'],grid['columns']
    if (rows,cols) not in ((6,8),(8,12)) or not (math.isfinite(w) and math.isfinite(h) and w > 0 and h > 0):
        raise DetectionError('This prototype requires a finite 6 by 8 or 8 by 12 feature-plane model.')
    pitch = float(grid['pitch_mm']); x0,y0 = grid['first_center_mm']
    wells = np.array([[x0+c*pitch,y0+r*pitch,0.] for r in range(rows) for c in range(cols)],float)
    rim = np.array([[0,0,0],[w,0,0],[w,h,0],[0,h,0]],float)
    if not np.isfinite(wells).all() or pitch <= 0 or np.any(wells[:,:2] <= 0) or np.any(wells[:,:2] >= [w,h]):
        raise DetectionError('Well centers must lie within the modeled feature plane.')
    return rim,wells


def intersect(a,b,c,d):
    v = b-a; u = d-c
    matrix = np.column_stack([v,-u])
    if abs(np.linalg.det(matrix)) < 1e-6:
        raise DetectionError('Rim edges are degenerate')
    return a+np.linalg.solve(matrix,c-a)[0]*v


def rim_candidates(gray):
    """Conservative high-contrast contour detector; clipped rims are rejected."""
    _,mask = cv2.threshold(cv2.GaussianBlur(gray,(5,5),0),0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    found = []
    for binary in (mask,255-mask):
        contours,_ = cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if not .08*gray.size < cv2.contourArea(contour) < .9*gray.size:
                continue
            poly = cv2.approxPolyDP(contour,.008*cv2.arcLength(contour,True),True).reshape(-1,2).astype(float)
            if len(poly) not in (4,5) or not cv2.isContourConvex(poly.astype(np.float32)):
                continue
            if np.any(poly <= 2) or np.any(poly >= [gray.shape[1]-3,gray.shape[0]-3]):
                continue
            notch = None
            if len(poly) == 5:
                lengths = np.linalg.norm(np.roll(poly,-1,axis=0)-poly,axis=1)
                index = int(np.argmin(lengths))
                if lengths[index] > .3*np.median(lengths):
                    continue
                p = np.roll(poly,-index,axis=0)
                notch = intersect(p[-1],p[0],p[1],p[2])
                poly = np.array([notch,*p[2:]])
            if cv2.contourArea(poly.astype(np.float32),oriented=True) < 0:
                poly = poly[::-1]
            found.append((poly,notch))
    return found


def detect_features(gray,model,orientation_template=None):
    rim,wells = model_points(model)
    rows,cols=model['grid']['rows'],model['grid']['columns']
    scale = 5.
    width,height = model['feature_width_mm'],model['feature_height_mm']
    destination = rim[:,:2]*scale
    cue = model['orientation']; candidates = []
    for poly,notch in rim_candidates(gray):
        for rotation in range(4):
            ordered = np.roll(poly,-rotation,axis=0)
            if cue['kind'] == 'single_chamfer':
                if notch is None or np.linalg.norm(ordered[0]-notch) > 1:
                    continue
            elif cue['kind'] != 'template' or orientation_template is None:
                continue
            homography = cv2.getPerspectiveTransform(ordered.astype(np.float32),destination.astype(np.float32))
            warped = cv2.warpPerspective(gray,homography,(round(width*scale),round(height*scale)))
            if cue['kind'] == 'template':
                x,y,w,h = np.rint(np.array(cue['rectangle_mm'])*scale).astype(int)
                if min(x,y)<0 or min(w,h)<=0:
                    raise DetectionError('Orientation template rectangle must be inside the feature plane')
                crop = warped[y:y+h,x:x+w]
                if crop.shape != (h,w) or np.std(crop)<5 or np.std(orientation_template)<5:
                    continue
                template = cv2.resize(orientation_template,(w,h))
                score = float(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED)[0,0])
                if score < .85:
                    continue
            _,binary = cv2.threshold(warped,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
            contours,_ = cv2.findContours(binary,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
            matches = {}; diameter = model['grid']['well_diameter_mm']
            for contour in contours:
                area = cv2.contourArea(contour); perimeter = cv2.arcLength(contour,True)
                nominal = math.pi*(diameter*scale/2)**2
                if not .55*nominal < area < 1.4*nominal or perimeter == 0 or 4*math.pi*area/perimeter**2 < .65:
                    continue
                moments = cv2.moments(contour)
                center = np.array([moments['m10']/moments['m00'],moments['m01']/moments['m00']])/scale
                distances = np.linalg.norm(wells[:,:2]-center,axis=1)
                index = int(np.argmin(distances))
                if distances[index] > 1.2:
                    continue
                if index not in matches or distances[index] < matches[index][0]:
                    matches[index] = (float(distances[index]),center*scale)
            if len(matches) < math.ceil(rows*cols*5/6) or len({i//cols for i in matches}) != rows or len({i%cols for i in matches}) != cols:
                continue
            indices = sorted(matches)
            rectified = np.array([matches[i][1] for i in indices],float)
            image_wells = cv2.perspectiveTransform(rectified.reshape(-1,1,2),np.linalg.inv(homography)).reshape(-1,2)
            candidates.append(dict(rim_px=ordered,well_indices=indices,well_px=image_wells))
    if len(candidates) != 1:
        raise DetectionError(f'No unique rim, {rows*cols}-well grid and orientation match; ambiguous or insufficient evidence.')
    return candidates[0]


def estimate_pose(features,model,k):
    _,wells = model_points(model)
    # Rim geometry selects correspondences. Fit metric pose to the well centers
    # only: base-skirt corners and well rims must not be assumed coplanar.
    objects = wells[features['well_indices']]; pixels = features['well_px']
    ok,rvecs,tvecs,_ = cv2.solvePnPGeneric(objects,pixels,k,None,flags=cv2.SOLVEPNP_IPPE)
    candidates = []
    if not ok:
        raise DetectionError('Planar pose estimation failed')
    for rvec,tvec in zip(rvecs,tvecs):
        rotation,_ = cv2.Rodrigues(rvec)
        if np.min((objects@rotation.T+tvec.reshape(3))[:,2]) <= 0:
            continue
        projected,_ = cv2.projectPoints(objects,rvec,tvec,k,None)
        error = np.linalg.norm(projected.reshape(-1,2)-pixels,axis=1)
        candidates.append((float(np.sqrt(np.mean(error**2))),float(error.max()),rvec,tvec,rotation))
    candidates.sort(key=lambda c:c[0])
    if not candidates or candidates[0][0] > 1.2 or candidates[0][1] > 3:
        raise DetectionError('Measured grid does not support a consistent metric pose')
    best = candidates[0]
    if len(candidates)>1:
        angle = math.degrees(math.acos(np.clip((np.trace(best[4].T@candidates[1][4])-1)/2,-1,1)))
        if candidates[1][0]-best[0] < .15 and angle > 2:
            raise DetectionError('Two planar poses fit similarly; viewpoint is ambiguous')
    rvec,tvec = cv2.solvePnPRefineLM(objects,pixels,k,None,best[2],best[3])
    rotation,_ = cv2.Rodrigues(rvec)
    projected,_ = cv2.projectPoints(objects,rvec,tvec,k,None)
    errors = np.linalg.norm(projected.reshape(-1,2)-pixels,axis=1)
    transform = np.eye(4);transform[:3,:3]=rotation;transform[:3,3]=tvec.reshape(3)
    if not np.isfinite(transform).all() or np.min((objects@rotation.T+tvec.reshape(3))[:,2])<=0 or errors.max()>3 or np.sqrt(np.mean(errors**2))>1.2:
        raise DetectionError('Refined pose is invalid')
    return dict(T_camera_plate=transform.tolist(),reprojection_rmse_px=float(np.sqrt(np.mean(errors**2))),
                reprojection_max_px=float(errors.max()),matched_wells=len(objects))


def circle_polygons(model,pose,k):
    transform = np.asarray(pose['T_camera_plate'])
    rvec,_=cv2.Rodrigues(transform[:3,:3]);tvec=transform[:3,3]
    polygons=[]
    for circle in model['virtual_circles']:
        center=finite_array(circle['center_mm'],(2,),'virtual circle center')
        radius=float(circle['radius_mm'])
        if not math.isfinite(radius) or radius <= 0:
            raise DetectionError('Invalid virtual circle radius')
        angles=np.linspace(0,2*math.pi,96,endpoint=False)
        points=np.column_stack([center[0]+radius*np.cos(angles),center[1]+radius*np.sin(angles),np.zeros(96)])
        pixels,_=cv2.projectPoints(points,rvec,tvec,k,None)
        polygons.append(dict(label=circle['label'],pixels_undistorted=pixels.reshape(-1,2).tolist()))
    return polygons


def analyze(image,model,camera,orientation_template=None):
    k,d=camera_parameters(camera,image.shape)
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image.copy()
    undistorted=cv2.undistort(gray,k,d)
    features=detect_features(undistorted,model,orientation_template)
    pose=estimate_pose(features,model,k); polygons=circle_polygons(model,pose,k)
    overlay=cv2.cvtColor(undistorted,cv2.COLOR_GRAY2BGR)
    cv2.polylines(overlay,[np.rint(features['rim_px']).astype(np.int32)],True,(0,210,70),2)
    for point in features['well_px']:
        cv2.circle(overlay,tuple(np.rint(point).astype(int)),2,(0,210,70),-1)
    for circle,color in zip(polygons,[(0,190,255),(255,180,30)]):
        cv2.polylines(overlay,[np.rint(circle['pixels_undistorted']).astype(np.int32)],True,color,2)
    cv2.putText(overlay,'OFFLINE - virtual landmarks only',(18,30),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,200,255),2)
    total=model['grid']['rows']*model['grid']['columns']
    cv2.putText(overlay,f"{pose['matched_wells']}/{total} wells | reprojection {pose['reprojection_rmse_px']:.3f} px",(18,58),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,200,255),1)
    result=dict(offline_only=True,motion_authorized=False,source='measured_plate_geometry',
                model_id=model['id'],model_validated=model.get('validated',False),
                calibration_id=camera['calibration_id'],camera_validated=camera.get('validated',False),
                synthetic=camera.get('synthetic',False),coordinate_frame='opencv_camera_mm',pose=pose,
                virtual_circles=polygons,features=dict(rim_corners_undistorted_px=features['rim_px'].tolist(),
                well_indices=features['well_indices'],well_centers_undistorted_px=features['well_px'].tolist(),
                orientation=model['orientation']['kind']),
                live_integration_blockers=['Offline prototype only; not published as a robot target.'])
    if not result['model_validated']:
        result['live_integration_blockers'].append('Physical plate model and orientation cue are unverified.')
    if not result['camera_validated']:
        result['live_integration_blockers'].append('Camera intrinsics are not validated for this image.')
    if model.get('reference_mapping_validated') is not True:
        result['live_integration_blockers'].append('Virtual-circle relationship to the taught two-disk grasp is unverified.')
    return result,overlay
