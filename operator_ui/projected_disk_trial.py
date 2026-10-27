"""Supervised calibration commissioning: one 2 mm XY pilot, never Z/yaw/grip.

Uses projected disk centers with the existing vendor XY camera transform.
Projected disk radii are NOT supplied to the vendor depth or grasp solver.
No calibration/alignment target is published by this preliminary trial.
"""
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

import cv2
import numpy as np
import teach
from autonomy import GuardedService, TransferError, check_path, number, wrap
from edge_center import verify_response

ROOT=Path(__file__).resolve().parent.parent
VISION=ROOT/'Pick and Hold/Align/plate_pose'
if str(VISION) not in sys.path: sys.path.insert(0,str(VISION))
from live_projection import Tracker
from multiview_rim import commissioned_tracker
from grid_pattern import GridPatternTracker,commissioned_grid_tracker
from vision import DetectionError

REFERENCE=ROOT/'operator_ui/reports/plate_projection_taught_48/result.json'
STEP_MM,SPEED=2.,5.


def same_pose(a,b):
    return all(abs(number(a.get(k),k)-number(b.get(k),k))<=.1 for k in ('X','Y','Z')) and abs(wrap(a['Rz']-b['Rz']))<=.05


def validate_request(body):
    if not isinstance(body,dict) or any(body.get(k) is not True for k in ('confirm','cell_clear','empty_gripper')):
        raise TransferError('Confirm E-stop supervision, empty jaws and clear 2 mm XY camera pilot.')
    pose={k:number(body.get('expected_start',{}).get(k),k) for k in ('X','Y','Z','Rz')}
    mode=body.get('tracking_mode','rim')
    if mode not in ('rim','grid_pattern','anchored_grid','height_referenced_grid'):raise TransferError('Unknown projected-disk tracking mode.')
    finish=body.get('finish_centering',False)
    if not isinstance(finish,bool):raise TransferError('finish_centering must be a boolean.')
    if finish and mode not in ('anchored_grid','height_referenced_grid'):raise TransferError('Fine centering requires the fixed-height grid reference.')
    burst=body.get('burst_frames',1)
    if type(burst) is not int or burst not in (1,5):raise TransferError('Burst must contain one or five frames.')
    if burst==5 and mode not in ('anchored_grid','height_referenced_grid'):raise TransferError('Burst capture requires the fixed-height grid reference.')
    scale_search=body.get('scale_search',False)
    if not isinstance(scale_search,bool) or (scale_search and mode not in ('anchored_grid','height_referenced_grid')):
        raise TransferError('Scale initialization requires the anchored grid tracker.')
    return dict(expected_start=pose,tracking_mode=mode,finish_centering=finish,burst_frames=burst,scale_search=scale_search)


def pilot_target(pose,error,finish_centering=False):
    error=np.asarray(error,float)
    if error.shape!=(2,) or not np.isfinite(error).all(): raise TransferError('Invalid XY correction')
    distance=float(np.linalg.norm(error))
    if finish_centering:
        if not .75<distance<=70:raise TransferError('Fine XY step requires an error above 0.75 mm and below 70 mm.')
        step=min(STEP_MM,.7*distance)
    else:
        if not 3<=distance<=70: raise TransferError('Pilot requires a 3-70 mm estimated centering error.')
        step=STEP_MM
    delta=error*step/distance
    return {**pose,'X':pose['X']+float(delta[0]),'Y':pose['Y']+float(delta[1])}


class Perception:
    def __init__(self,tracking_mode='rim',burst_frames=1,scale_search=False):
        self.burst_frames=burst_frames
        self.last_measurement_pose=None
        self.reference=json.loads(REFERENCE.read_text())
        saved=self.reference['images']['target'];path=Path(saved['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=saved['sha256']:
            raise TransferError('Projected-disk reference image changed.')
        image=cv2.imread(str(path))
        if image is None: raise TransferError('Missing projection reference image.')
        self.native_size=[image.shape[1],image.shape[0]]
        if tracking_mode=='grid_pattern':
            self.tracker=GridPatternTracker(image,self.reference['corners_native_px']['target'],
                {c['label']:c['pixels'] for c in self.reference['virtual_circles']})
        elif tracking_mode=='anchored_grid':
            self.tracker=commissioned_grid_tracker(ROOT,self.reference,image)
            self.tracker.template_scale_search=scale_search
        elif tracking_mode=='rim':self.tracker=commissioned_tracker(ROOT,self.reference,image)
        else:raise TransferError('Unknown projected-disk tracking mode.')
        self.cfg=next(c for c in teach._configs() if c['name']=='Wide')
        if self.native_size!=[int(v) for v in self.cfg['cam_param'][10:12]]:
            raise TransferError('Reference resolution differs from calibrated camera.')
        ok,_=teach.selftest()
        if not ok: raise TransferError('Vendor camera-math selftest failed.')

    def measure(self,frame,pose):
        if [frame.shape[1],frame.shape[0]]!=self.native_size:
            raise TransferError('Capture resolution changed.')
        # A prior image estimate is a stationary initializer, not a motion
        # prediction. Reacquire after robot motion without widening ECC bounds.
        if (self.last_measurement_pose is not None
                and not same_pose(self.last_measurement_pose,pose)
                and hasattr(self.tracker,'previous_verified_seed')):
            self.tracker.previous_verified_seed=None
        tracked=self.tracker.track(frame)
        self.last_measurement_pose=dict(pose)
        centers={}
        scale=frame.shape[1]/tracked['image_size_px'][0]
        for c in tracked['virtual_circles']:
            p=np.array(c['pixels'])*scale
            fit,_,rank,_=np.linalg.lstsq(np.column_stack([2*p,np.ones(len(p))]),np.sum(p*p,axis=1),rcond=None)
            if rank!=3 or not np.isfinite(fit).all(): raise TransferError('Invalid projected disk center.')
            centers[c['label']]=fit[:2]
        big,small=centers['large'],centers['small']
        midpoint=(big+small)/2
        angle=float(np.degrees(np.arctan2(*(small-big)[::-1]))%360)
        mark=[float(midpoint[0]),float(midpoint[1]),angle]
        current=teach.mark_in_robot_pose(self.cfg,mark)
        offset=np.zeros(6);offset[:2]=current[:2]-self.cfg['model_mark_robot'][:2]
        correction=teach.new_acc_pose([pose['X'],pose['Y'],pose['Z'],0,0,pose['Rz']],offset)
        error=correction[:2]-[pose['X'],pose['Y']]
        return dict(mark=mark,error_xy_mm=error.tolist(),tracking=tracked,
                    depth_estimated=False,grasp_target_created=False)


def observe(guard,cam,perception,record):
    pose=guard.pose_mm()
    frames=[];hashes=[]
    for _ in range(perception.burst_frames):
        frame=cam.snap();frames.append(frame)
        hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
        if not same_pose(pose,guard.pose_mm()):raise TransferError('Arm moved during capture.')
    if len(frames)>1:
        if len(set(hashes))<3:raise DetectionError('Burst did not contain enough distinct camera frames.')
        frame=np.median(frames,axis=0).astype(np.uint8)
    if not same_pose(pose,guard.pose_mm()): raise TransferError('Arm moved during capture.')
    if len(frames)>1:
        path=cam.save(frame,prefix=f'projected_grid_burst_{time.time_ns()}')
        record('stationary_image_burst',pose=pose,frame_count=len(frames),source_hashes=hashes,median_image=path)
    measurement=perception.measure(frame,pose)
    if not same_pose(pose,guard.pose_mm()): raise TransferError('Arm moved during projection.')
    record('observation',pose=pose,measurement=measurement)
    return pose,measurement


def stationary_observation(guard,cam,perception,record):
    origin=guard.pose_mm();accepted=[];deadline=time.monotonic()+20.
    while time.monotonic()<deadline:
        # Pose/fault/Stop checks remain active during every stationary retry.
        if not same_pose(origin,guard.pose_mm()):raise TransferError('Arm moved during stationary vision rechecks.')
        try:
            pose,measurement=observe(guard,cam,perception,record)
        except DetectionError as error:
            record('vision_rejected_stationary',error=str(error),pose=guard.pose_mm())
            accepted=[]
            time.sleep(.15)
            continue
        if not same_pose(origin,pose):raise TransferError('Arm moved during stationary vision rechecks.')
        if any(np.linalg.norm(np.array(previous['error_xy_mm'])-measurement['error_xy_mm'])>.25 for previous in accepted):
            raise TransferError('Stationary projected-disk readings disagree.')
        accepted.append(measurement)
        if len(accepted)==3:return pose,measurement
    raise TransferError('No three consecutive verified plate observations within 20 seconds; arm remains stopped.')


def pilot(run,svc,cam,params,config,perception=None):
    run.target=None
    guard=GuardedService(svc,run,params)
    folder=ROOT/'operator_ui/reports/projected_disk_pilot'
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.jsonl')
    def record(event,**fields):
        with path.open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(timestamp=time.time(),event=event,**fields))+'\n')
    motion_requested=False
    try:
        guard._preflight()
        if not same_pose(config['expected_start'],guard.pose_mm()):
            raise TransferError('Arm moved from the reviewed pilot start; prepare a fresh trial.')
        if config.get('tracking_mode')=='height_referenced_grid':
            from projected_alignment import perception_at_height
            perception,reference,provenance=perception_at_height()
            if abs(guard.pose_mm()['Z']-reference['observation_z_mm'])>.1:
                raise TransferError('Height-matched centering requires the verified observation height.')
            record('height_matched_reference',reference=provenance)
        else:
            perception=perception or Perception(config.get('tracking_mode','rim'),config.get('burst_frames',1),config.get('scale_search',False))
        pose,before=stationary_observation(guard,cam,perception,record)
        finish=config.get('finish_centering',False)
        if finish and np.linalg.norm(before['error_xy_mm'])<=.75:
            actual,after=stationary_observation(guard,cam,perception,record)
            if not same_pose(pose,actual) or np.linalg.norm(np.array(before['error_xy_mm'])-after['error_xy_mm'])>.25:
                raise TransferError('Final XY centering checks disagree.')
            if np.linalg.norm(after['error_xy_mm'])>.75:raise TransferError('Final XY centering is outside tolerance.')
            result=dict(ok=True,pilot_verified=False,xy_centered=True,motion_requested=False,
                calibration_complete=False,grasp_target_created=False,before=before,after=after,
                start=pose,final_pose=actual,log_file=str(path))
            record('xy_centered',result=result)
            run.say('Projected landmarks centered within 0.75 mm estimated XY error. Height calibration and alignment remain unverified.','good')
            return result
        point=pilot_target(pose,before['error_xy_mm'],finish_centering=finish)
        check_path(pose,point,svc.joints() or {},params,guard.path_envelope)
        telemetry=guard.torque_report()
        number(telemetry.get('e1_position'),'E1 position')
        if number(telemetry.get('e1_torque'),'E1 torque')<=-100:
            raise TransferError('Gripper may be holding an object; empty jaws required.')
        if not same_pose(pose,guard.pose_mm()): raise TransferError('Pilot start changed before motion.')
        record('movement_requested',start=pose,target=point,speed=SPEED)
        run.say(f"Projected-disk pilot: X {point['X']:.3f}, Y {point['Y']:.3f}, height/wrist fixed, speed 5")
        motion_requested=True
        guard.move_cartesian(point['X'],point['Y'],point['Z'],point['Rz'],SPEED,'linear')
        actual,after=stationary_observation(guard,cam,perception,record)
        if abs(actual['Z']-pose['Z'])>.1 or abs(wrap(actual['Rz']-pose['Rz']))>.05:
            raise TransferError('Height or wrist changed during fixed-pose pilot.')
        delta=np.array([actual['X']-pose['X'],actual['Y']-pose['Y']])
        verify_response(before['error_xy_mm'],after['error_xy_mm'],delta)
        if np.linalg.norm(after['error_xy_mm'])>=np.linalg.norm(before['error_xy_mm']):
            raise TransferError('Projected-disk centering error did not improve.')
        result=dict(ok=True,pilot_verified=True,calibration_complete=False,grasp_target_created=False,
            before=before,after=after,start=pose,final_pose=actual,log_file=str(path))
        record('completed',result=result)
        run.say('Projected-disk XY pilot passed. Stopped for review; full calibration and alignment have not run.','good')
        return result
    except Exception as ex:
        result=dict(ok=False,error=str(ex),motion_requested=motion_requested,
                    calibration_complete=False,grasp_target_created=False,log_file=str(path))
        record('stopped',result=result)
        run.state='stopped' if run.stopped() else 'error';run.say(str(ex),'err')
        return result


if __name__=='__main__':
    # Read-only preparation. Live motion is available only through the Runner
    # endpoint, with its operator confirmations and sequence exclusivity.
    import argparse
    from urllib.request import urlopen
    parser=argparse.ArgumentParser(description='Prepare projected-disk XY pilot; no movement.')
    parser.add_argument('--preview-output',type=Path,required=True)
    parser.add_argument('--tracking-mode',choices=('rim','grid_pattern','anchored_grid'),default='rim')
    args=parser.parse_args()
    with urlopen('http://127.0.0.1:5002/state',timeout=5) as response: first=json.load(response)
    with urlopen('http://127.0.0.1:5002/frame',timeout=5) as response:
        if response.headers.get('X-Error'): raise TransferError(response.headers['X-Error'])
        frame=cv2.imdecode(np.frombuffer(response.read(),np.uint8),cv2.IMREAD_COLOR)
    with urlopen('http://127.0.0.1:5002/state',timeout=5) as response: state=json.load(response)
    pose=state['robot']['pose_mm']
    if not same_pose(first['robot']['pose_mm'],pose) or state['camera'].get('age_s',999)>.8:
        raise TransferError('Stale/moving preview observation.')
    measurement=Perception(args.tracking_mode).measure(frame,pose)
    target=pilot_target(pose,measurement['error_xy_mm'])
    params=json.loads((ROOT/'operator_ui/robot_params.json').read_text())
    envelope={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    joints=check_path(pose,target,state['robot']['joints'],params,envelope)
    result=dict(preview_only=True,motion_started=False,start=pose,target=target,speed=SPEED,
                expected_joints=joints,measurement=measurement,timestamp=time.time())
    args.preview_output.parent.mkdir(parents=True,exist_ok=True)
    args.preview_output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='measurement'},indent=2))
