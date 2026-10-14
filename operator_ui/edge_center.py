"""Supervised edge-based image centering. Fixed Z/Rz; no grasp operations."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time

import cv2
import numpy as np

from autonomy import GuardedService, TransferError, check_path, number, wrap
from plate_edges import detect_plate, annotate, ordered_corners

MAX_VIEWS, MAX_SECONDS, MAX_TRAVEL_MM = 18, 120., 70.
FIRST_STEP_MM, STEP_MM, SPEED, GAIN = 2., 5., 5., .7
CENTER_PX, CENTER_MM = 8., .75


def validate_request(body):
    if not isinstance(body,dict):
        raise TransferError('JSON object required')
    if any(body.get(k) is not True for k in ('confirm','cell_clear','empty_gripper','outline_verified')):
        raise TransferError('Confirm E-stop supervision, clear XY travel, empty gripper and the previewed plate outline')
    gap=number(body.get('camera_distance_mm'),'camera-to-plate distance (not TCP Z)')
    if not 205 <= gap <= 240:
        raise TransferError('camera-model working distance must be 205-240 mm; this is NOT TCP Z')
    return dict(camera_distance_mm=gap)


class CameraMapping:
    """Differential form of the existing fitted eye-camera model.

    At fixed Z/Rz and object depth, the camera lever arm and tilt terms cancel
    between two image points. No marker is detected or required here.
    """
    def __init__(self):
        import teach
        import aruco_detect
        ok,_=teach.selftest()
        if not ok:
            raise TransferError('vendor camera-math selftest failed; no motion')
        with open(teach.CAL_PATH,encoding='utf-8-sig') as f:
            fit=json.load(f)['eye_cam_fit']
        self.stamp=fit.get('fitted')
        if not self.stamp or fit.get('frame') != 'tool (rotates with Rz)':
            raise TransferError('a fitted tool-mounted camera model is required')
        if not 0 <= number(fit.get('rms_mm'),'camera fit residual') <= 4:
            raise TransferError('camera fit residual exceeds the existing calibration quality gate')
        self.yaw=number(fit.get('yaw_offset_deg'),'camera yaw calibration')
        self.mirror=number(fit.get('mirror_f'),'camera mirror calibration')
        self.scale=number(fit.get('u_scale'),'camera scale calibration')
        if self.mirror not in (-1,1) or not .5 <= self.scale <= 2:
            raise TransferError('invalid camera scale/mirror calibration')
        cfg=teach._configs()[0]
        self.K,self.dist,_=aruco_detect.intrinsics(cfg)
        self.size=[int(v) for v in cfg['cam_param'][10:12]]
        if not np.all(np.isfinite(self.K)) or not np.all(np.isfinite(self.dist)):
            raise TransferError('invalid camera intrinsics')

    def correction(self,detection,rz,gap):
        if list(detection['image_size']) != self.size:
            raise TransferError('camera frame resolution differs from calibrated intrinsics; no motion')
        gap=number(gap,'camera distance')
        if not 205 <= gap <= 240:
            raise TransferError('camera distance outside 205-240 mm')
        pts=np.asarray([detection['center_px'],detection['image_center_px']],np.float64)
        if pts.shape != (2,2) or not np.all(np.isfinite(pts)):
            raise TransferError('invalid image-center coordinates')
        n=cv2.undistortPoints(pts.reshape(-1,1,2),self.K,self.dist).reshape(2,2)
        camera=(n[0]-n[1])*gap*self.scale
        camera[1]*=self.mirror
        a=math.radians(number(rz,'wrist yaw')+self.yaw)
        return np.array([[math.cos(a),-math.sin(a)],[math.sin(a),math.cos(a)]])@camera


def validate_detection(d):
    if not d.get('detected') or d.get('candidate_count') != 1:
        raise TransferError(d.get('reason') or 'plate outline missing or ambiguous')
    p=np.asarray(d.get('corners'),float)
    size=np.asarray(d.get('image_size'),float)
    if p.shape!=(4,2) or size.shape!=(2,) or not np.all(np.isfinite(p)) or not np.all(np.isfinite(size)):
        raise TransferError('invalid plate corners')
    if np.any(p<4) or np.any(p[:,0]>size[0]-5) or np.any(p[:,1]>size[1]-5):
        raise TransferError('plate corners clipped by the image')
    support=d.get('side_support',[])
    if len(support)!=4 or any(not .65 <= number(v,'edge support') <= 1 for v in support):
        raise TransferError('all four plate edges must be supported')
    for key in ('center_px','image_center_px','offset_px'):
        v=np.asarray(d.get(key),float)
        if v.shape!=(2,) or not np.all(np.isfinite(v)):
            raise TransferError('invalid '+key)
    if np.linalg.norm(np.asarray(d['center_px'])-d['image_center_px']-d['offset_px'])>.01:
        raise TransferError('inconsistent image center/offset')
    number(d.get('angle_image_deg'),'plate angle')


def same_plate(a,b,stationary=False):
    if a['image_size'] != b['image_size']:
        raise TransferError('frame size changed during centering')
    angle=(b['angle_image_deg']-a['angle_image_deg']+90)%180-90
    if abs(angle)>2:
        raise TransferError('plate orientation changed with wrist fixed; inspect object/detection')
    def sides(d):
        p=ordered_corners(d['corners'])
        return np.sort(np.linalg.norm(np.roll(p,-1,axis=0)-p,axis=1))
    ratio=sides(b)/sides(a)
    if np.any(ratio<.95) or np.any(ratio>1.05):
        raise TransferError('plate outline changed size; no further motion')
    if stationary and np.linalg.norm(np.asarray(a['center_px'])-b['center_px'])>CENTER_PX:
        raise TransferError('stationary edge detections disagree; no motion')


def verify_response(before_error,after_error,actual_delta):
    """The first pilot and every substantial step must match camera direction."""
    step=float(np.linalg.norm(actual_delta))
    if step < .75:
        return
    observed=np.asarray(before_error)-np.asarray(after_error)
    direction=np.asarray(actual_delta)/step
    forward=float(observed@direction)
    sideways=float(np.linalg.norm(observed-forward*direction))
    if forward < .2*step or sideways > max(.8,.6*step) or np.linalg.norm(observed)>2*step+.8:
        raise TransferError('image response disagrees with commanded XY move; inspect camera mapping/plate before retry')


def save_overlay(cam,frame,detection,edges):
    raw=Path(cam.save(frame,prefix=f'plate_edges_{time.time_ns()}'))
    output=raw.with_name(raw.stem+'_overlay.jpg')
    if not cv2.imwrite(str(output),annotate(frame,detection,edges)):
        raise TransferError('could not save plate-edge overlay')
    return str(output)


def preview(run,cam):
    try:
        if run.stopped():
            raise TransferError('preview stopped')
        frame=cam.snap()
        detection,edges=detect_plate(frame)
        run.detection_path=save_overlay(cam,frame,detection,edges)
        run.detection_ts=time.time()
        validate_detection(detection)
        run.say(f"EDGE PREVIEW: offset {detection['offset_px'][0]:+.1f}, "
                f"{detection['offset_px'][1]:+.1f} px; angle {detection['angle_image_deg']:+.2f} deg. "
                'Review all four sides/corners. No robot motion; angle is image-only.','good')
        return dict(ok=True,preview=True,detection=detection)
    except Exception as ex:
        run.state='stopped' if run.stopped() else 'error'
        run.say(str(ex),'err')
        return dict(ok=False,error=str(ex))


def center(run,svc,cam,params,config,mapper=None):
    run.target=None  # centering changes the view; never reuse a stale grasp target
    guard=GuardedService(svc,run,params)
    started=time.monotonic()
    moves=0
    travel=0.
    last=None
    previous_move=None
    stable=0
    try:
        mapper=mapper or CameraMapping()
        gap=number(config['camera_distance_mm'],'camera-to-plate distance')
        if not 205<=gap<=240:
            raise TransferError('camera distance outside commissioned 205-240 mm range')
        start=guard.pose_mm()
        run.say(f'Edge center v1: plate outline -> image center, fixed Z {start["Z"]:.3f} / '
                f'Rz {start["Rz"]:.3f}; camera gap {gap:g} mm; model {mapper.stamp}')
        for view in range(1,MAX_VIEWS+1):
            guard._preflight()
            if time.monotonic()-started>MAX_SECONDS:
                raise TransferError('edge-centering time budget exhausted')
            pose=guard.pose_mm()
            if abs(pose['Z']-start['Z'])>.1 or abs(wrap(pose['Rz']-start['Rz']))>.05:
                raise TransferError('Z or wrist changed during fixed-view centering')
            check_path(pose,pose,svc.joints() or {},params,svc.envelope)
            frame=cam.snap()
            d,edges=detect_plate(frame)
            after=guard.pose_mm()
            if any(abs(after[k]-pose[k])>.1 for k in ('X','Y','Z')) or abs(wrap(after['Rz']-pose['Rz']))>.05:
                raise TransferError('robot moved during image capture')
            run.detection_path=save_overlay(cam,frame,d,edges)
            run.detection_ts=time.time()
            validate_detection(d)
            error=np.asarray(mapper.correction(d,pose['Rz'],gap),float)
            if error.shape!=(2,) or not np.all(np.isfinite(error)):
                raise TransferError('invalid pixel-to-robot correction')
            mm=float(np.linalg.norm(error))
            px=float(np.linalg.norm(d['offset_px']))
            done=px<=CENTER_PX and mm<=CENTER_MM
            if last:
                if previous_move is None and any(abs(pose[k]-last['pose'][k])>.1 for k in ('X','Y')):
                    raise TransferError('robot moved between stationary edge confirmations')
                same_plate(last['d'],d,stationary=previous_move is None)
                if previous_move is not None:
                    actual=np.array([pose['X']-last['pose']['X'],pose['Y']-last['pose']['Y']])
                    if not done:
                        verify_response(last['error'],error,actual)
                    if mm>float(np.linalg.norm(last['error']))+.5:
                        raise TransferError('image-centering error increased; no further motion')
                    run.say('Center is within tolerance after the step' if done else
                            'Observed image shift agrees with XY correction')
            run.say(f'View {view}: center offset {px:.1f} px / approx {mm:.2f} mm; '
                    f'image angle {d["angle_image_deg"]:+.2f} deg (not corrected)')
            stable=stable+1 if done and previous_move is None else (1 if done else 0)
            if stable>=2:
                run.say('PLATE IMAGE CENTERED in two fresh views. No wrist alignment, Z calibration or grasp target.','good')
                return dict(ok=True,centered=True,grasp_target_created=False,detection=d,
                            pose_mm=pose,moves=moves,views=view,elapsed_s=round(time.monotonic()-started,2))
            had_previous=last is not None
            last=dict(d=d,error=error,pose=pose)
            previous_move=None
            if done or not had_previous:
                run.say('Confirming the outline with a second stationary image')
                continue
            goal={**pose,'X':pose['X']+float(error[0]),'Y':pose['Y']+float(error[1])}
            # Refuse an impossible final center BEFORE moving toward a limit.
            check_path(pose,goal,svc.joints() or {},params,svc.envelope)
            step=min(FIRST_STEP_MM if moves==0 else STEP_MM,GAIN*mm)
            delta=error/mm*step
            if travel+step>MAX_TRAVEL_MM:
                raise TransferError('edge-centering travel budget exhausted')
            if moves==0:
                telemetry=guard.torque_report()
                number(telemetry.get('e1_position'),'E1 position')
                if number(telemetry.get('e1_torque'),'E1 torque')<=-100:
                    raise TransferError('gripper may be holding an object; empty jaws required')
            point={**pose,'X':pose['X']+float(delta[0]),'Y':pose['Y']+float(delta[1])}
            run.say(f'Checked XY {"pilot" if moves==0 else "step"}: '
                    f'dX {delta[0]:+.2f}, dY {delta[1]:+.2f} mm, Z/Rz fixed @ {SPEED:g}')
            guard.move_cartesian(point['X'],point['Y'],point['Z'],point['Rz'],SPEED,'linear')
            moves+=1
            travel+=step
            previous_move=point
        raise TransferError('edge-centering view budget exhausted; not centered')
    except Exception as ex:
        run.target=None
        run.state='stopped' if run.stopped() else 'error'
        run.say(str(ex),'err')
        return dict(ok=False,error=str(ex),moves=moves,grasp_target_created=False)
