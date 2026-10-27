"""Supervised upward observation-height transfer, at most 2 mm per request.

Uses a successful physical two-disk observation Z plus measured plate-height
difference on the same support. Virtual disk radii never estimate depth. This
does not create an alignment/grasp target or mark full calibration complete.
"""
import hashlib
import json
import time
import uuid
import cv2
import numpy as np
from projected_disk_trial import ROOT, Perception, same_pose, observe, DetectionError
from autonomy import GuardedService, TransferError, check_path, number, wrap

SOURCE=ROOT/'operator_ui/reports/calibration/20261024_211431_04c13f94.jsonl'
MODEL=ROOT/'Pick and Hold/Align/plate_pose/plate_48_pending.json'
SPEED=5

class HeightPerception(Perception):
    """Track physical well/rim scale only, not the cross-plate disk mapping.

    Both local well-group fits, distributed support and plate geometry gates
    still apply. These measurements cannot be used to publish an XY/grasp target.
    """
    def __init__(self):
        super().__init__('anchored_grid',5)
        self.tracker.template_scale_search=True

    def measure(self,frame,pose):
        if [frame.shape[1],frame.shape[0]]!=self.native_size:
            raise TransferError('Capture resolution changed.')
        t=self.tracker
        if self.last_measurement_pose is None or not same_pose(self.last_measurement_pose,pose):
            t.previous_verified_seed=None
        seed=t.previous_verified_seed
        info=dict(method='previous_verified_initialization',accepted_pose=False)
        if seed is None:
            seed,info=t.initial_seed(frame)
        measured=t.anchor.track(frame,seed=seed)
        t.previous_verified_seed=np.array(measured['H_preview_from_reference_preview']).copy()
        self.last_measurement_pose=dict(pose)
        measured.pop('virtual_circles',None)
        measured.update(initialization=info or dict(method='measured_well_grid',accepted_pose=False),
            reference_frame='frozen_same_plate_anchor',anchor_sha256=t.anchor_hash,
            original_disk_mapping_validated=False)
        return dict(tracking=measured,depth_estimated=False,grasp_target_created=False,
                    purpose='Real-plate relative scale measurement only')

def stationary_observation(guard,cam,perception,record):
    origin=guard.pose_mm();accepted=[];deadline=time.monotonic()+20.
    while time.monotonic()<deadline:
        if not same_pose(origin,guard.pose_mm()):raise TransferError('Arm moved during stationary height checks.')
        try:
            pose,measurement=observe(guard,cam,perception,record)
        except DetectionError as ex:
            record('vision_rejected_stationary',error=str(ex),pose=guard.pose_mm())
            accepted=[];time.sleep(.15);continue
        corners=np.asarray(measurement['tracking']['corners_px'],float)
        if corners.shape!=(4,2) or not np.isfinite(corners).all():raise TransferError('Invalid height-check corners.')
        if any(np.linalg.norm(corners-previous,axis=1).max()>.8 for previous in accepted):
            raise TransferError('Stationary real-plate corners disagree.')
        accepted.append(corners)
        if len(accepted)==3:return pose,measurement
    raise TransferError('No three consecutive verified real-plate observations within 20 seconds; arm remains stopped.')

def validate_request(body):
    if not isinstance(body,dict) or any(body.get(k) is not True for k in
            ('confirm','cell_clear','empty_gripper','same_support')):
        raise TransferError('Confirm supervised clear upward path, empty jaws and unchanged plate support height.')
    return dict(expected_start={k:number(body.get('expected_start',{}).get(k),k)
                               for k in ('X','Y','Z','Rz')},
                reference_target_z=number(body.get('reference_target_z'),'reviewed reference Z'))

def reference():
    raw=SOURCE.read_bytes();events=[json.loads(s) for s in raw.decode().splitlines()]
    final=events[-1];result=final.get('result',{})
    if (final.get('event')!='completed' or result.get('ok') is not True
            or result.get('target',{}).get('converged') is not True
            or result['target'].get('config')!='Wide'):
        raise TransferError('Missing completed physical Wide reference.')
    model_raw=MODEL.read_bytes();h=json.loads(model_raw)['height_reference']
    original=number(h.get('original_two_disk_plate_height_mm'),'original plate height')
    current=number(h.get('well_plate_height_mm'),'current plate height')
    if original!=15. or current!=20.:
        raise TransferError('Physical plate measurements changed; review height reference.')
    source_z=number(result['calibration_pose']['Z'],'source observation Z')
    return dict(source_log=str(SOURCE),source_sha256=hashlib.sha256(raw).hexdigest(),
                height_model_sha256=hashlib.sha256(model_raw).hexdigest(),
                source_z=source_z,original_plate_height_mm=original,current_plate_height_mm=current,
                target_z=source_z+current-original,
                method='Transferred physical observation-height reference, same bottom support; not independent optical depth.')

def next_target(pose,target_z):
    if not 268.0<=pose['Z']<=target_z+.1 or not 268.<target_z<=300.:
        raise TransferError('Height trial outside the reviewed upward observation interval.')
    return dict(pose,Z=min(target_z,pose['Z']+2.))

def verify_scale(before,after,dz):
    if not 0.05<dz<=2.1:raise TransferError('Unexpected height step.')
    def sides(m):
        p=np.asarray(m['tracking']['corners_px'],float)
        if p.shape!=(4,2) or not np.isfinite(p).all():raise TransferError('Invalid measured plate corners.')
        return np.linalg.norm(np.roll(p,-1,axis=0)-p,axis=1)
    a,b=sides(before),sides(after)
    if np.any(a<=0):raise TransferError('Degenerate plate extent.')
    ratios=b/a;scale=float(np.median(ratios))
    if (not np.isfinite(ratios).all() or np.ptp(ratios)>.004
            or not 0<scale<.9995 or np.any(ratios>=1.0005)):
        raise TransferError('Plate scale did not shrink consistently after the upward step.')
    # Broad diagnostic range only, assuming approximately axial camera motion.
    # This is NOT an absolute depth calibration or a grasp height estimate.
    approximate_distance=dz*scale/(1-scale)
    if not 100.<approximate_distance<400.:
        raise TransferError('Observed scale change disagrees with this camera-height step.')
    return dict(side_scale_ratios=ratios.tolist(),median_scale=scale,
                approximate_axial_distance_before_mm=approximate_distance,
                absolute_depth_verified=False)

def pilot(run,svc,cam,params,config,perception=None):
    run.target=None
    guard=GuardedService(svc,run,params)
    folder=ROOT/'operator_ui/reports/projected_height_pilot';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.jsonl')
    def record(event,**data):
        with path.open('a',encoding='utf-8') as f:f.write(json.dumps(dict(timestamp=time.time(),event=event,**data),allow_nan=False)+'\n')
    moved=False
    try:
        guard._preflight();ref=reference()
        if abs(ref['target_z']-config['reference_target_z'])>.001:raise TransferError('Reviewed height reference changed.')
        if not same_pose(config['expected_start'],guard.pose_mm()):raise TransferError('Height-trial start changed.')
        p=perception or HeightPerception()
        p.tracker.template_scale_search=True
        record('reference',reference=ref,same_support_confirmed=True,config=config)
        start,before=stationary_observation(guard,cam,p,record)
        target=next_target(start,ref['target_z'])
        if abs(ref['target_z']-start['Z'])<=.1:
            actual,after=stationary_observation(guard,cam,p,record)
            if not same_pose(start,actual):raise TransferError('Pose changed during final height checks.')
            scale_result=None
        else:
            check_path(start,target,svc.joints() or {},params,guard.path_envelope)
            torque=guard.torque_report()
            e1=number(torque.get('e1_position'),'claw position')
            if number(torque.get('e1_torque'),'claw torque')<=-100:raise TransferError('Empty jaws required.')
            if not same_pose(start,guard.pose_mm()):raise TransferError('Start changed before upward motion.')
            record('movement_requested',start=start,target=target,speed=SPEED)
            run.say(f"Height-reference trial: raise to Z{target['Z']:.3f} mm, XY/wrist fixed, speed 5")
            moved=True
            guard.move_cartesian(target['X'],target['Y'],target['Z'],target['Rz'],SPEED,'linear')
            actual,after=stationary_observation(guard,cam,p,record)
            if (any(abs(actual[k]-start[k])>.1 for k in ('X','Y'))
                    or abs(wrap(actual['Rz']-start['Rz']))>.05):raise TransferError('XY or wrist changed during vertical trial.')
            if abs(number(guard.torque_report().get('e1_position'),'claw position')-e1)>.1:
                raise TransferError('Claw position changed during height trial.')
            scale_result=verify_scale(before,after,actual['Z']-start['Z'])
        reached=abs(actual['Z']-ref['target_z'])<=.1
        result=dict(ok=True,motion_requested=moved,pilot_verified=moved,
            height_reference_reached=reached,reference=ref,start=start,final_pose=actual,
            before=before,after=after,scale_response=scale_result,
            calibration_complete=False,absolute_depth_verified=False,grasp_target_created=False,log_file=str(path))
        result['original_disk_mapping_validated']=False
        record('completed',result=result)
        run.say('Transferred observation height reached and checked; XY must be rechecked before alignment.' if reached
                else 'Upward step and image-scale response passed. Stopped for review.','good')
        return result
    except Exception as ex:
        result=dict(ok=False,error=str(ex),motion_requested=moved,calibration_complete=False,
                    grasp_target_created=False,log_file=str(path))
        record('stopped',result=result)
        run.state='stopped' if run.stopped() else 'error';run.say(str(ex),'err')
        return result
