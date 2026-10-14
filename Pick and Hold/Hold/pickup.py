"""Supervised pickup verification. No hardware activity on import.

Owns the Runner through lift, visual approval and fresh snapshot. The marker
must remain observable. Plate pose is XYZ+yaw under an explicit level-plate
assumption, not a measured six-DOF pose. No release/retry/recovery motion.
"""
import copy
import math
import threading
import time
import uuid
from autonomy import GuardedService, TransferError, number, ensure_arrival, wrap


class PickupVerification:
    def __init__(self):
        self.lock=threading.RLock()
        self.event=threading.Event()
        self.invalidated_at=time.time()
        self.state={'phase':'idle','verified':False}
        self.answer=None

    def invalidate(self):
        with self.lock:
            self.invalidated_at=time.time()
            if self.state.get('verified'):
                self.state={'phase':'invalidated','verified':False}

    def public(self):
        with self.lock:
            result=copy.deepcopy(self.state)
            if result.get('verified') and time.time()-result['snapshot']['captured_at']>30:
                result['verified']=False;result['phase']='expired'
            return result

    def confirm(self,token,yes):
        with self.lock:
            if self.state.get('phase')!='awaiting_visual' or token!=self.state.get('token') or self.event.is_set():
                raise TransferError('No matching pending visual confirmation')
            if type(yes) is not bool:raise TransferError('Explicit visual confirmation required')
            self.answer=yes;self.event.set()

    @staticmethod
    def grip(svc,command):
        g=GuardedService.checked(svc.gripper_status())
        pos=number(g.get('e1_position'),'fresh E1 position')
        torque=number(g.get('e1_torque'),'fresh E1 torque')
        if not 0<=pos<=28 or not 0<=command<=28 or pos-command<=.15 or torque>=-100:
            raise TransferError('Grip unconfirmed: require valid E1, torque < -100 and position stall >0.15 mm')
        return {**g,'command_mm':command,'position_error_mm':pos-command,'confirmed':True,'sampled_at':time.time()}

    @staticmethod
    def observe(svc,cam,vision,mid,dz,tag):
        stamps=vision.model_stamps()
        if not stamps[0] or stamps[0]!=stamps[1]:raise TransferError('Camera/claw calibration stamps missing or inconsistent')
        cal=vision.W.CAL.get('marker_offsets',{}).get(str(mid),{})
        dx,dy,yawoff=[number(cal.get(k),'plate calibration '+k) for k in ('dx_mm','dy_mm','rel_yaw_deg')]
        p=svc.pose_mm()
        path=cam.save(cam.snap(),prefix='pickup_'+tag+'_'+uuid.uuid4().hex)
        end=svc.pose_mm();ensure_arrival(end,p)
        s=vision.solve(path,p['X'],p['Y'],p['Z'],p['Rz'],marker_id=mid)
        if not s.get('detected') or s.get('id')!=mid:raise TransferError('Plate marker missing/ambiguous; cannot verify pickup')
        xyz=[number(v,'marker XYZ') for v in s['marker_world']]
        if len(xyz)!=3:raise TransferError('Invalid marker pose')
        h=number(s.get('H_mm'),'camera distance')
        if not 205<=h<=240:raise TransferError('Marker outside commissioned camera distance 205..240 mm; pickup pose measurement unavailable')
        center=vision.view_center_world(p['X'],p['Y'],p['Rz'],h)
        if math.hypot(xyz[0]-center[0],xyz[1]-center[1])>5:raise TransferError('Marker outside commissioned centered view; no automatic camera repositioning while holding')
        yaw=number(s.get('marker_yaw_deg'),'marker yaw');a=math.radians(yaw)
        plate={'X':xyz[0]+math.cos(a)*dx-math.sin(a)*dy,'Y':xyz[1]+math.sin(a)*dx+math.cos(a)*dy,'Z':xyz[2]+dz,'Rz':wrap(yaw+yawoff)}
        return dict(tcp=p,plate=plate,image=path,observed_at=time.time(),calibration_stamps=list(stamps))

    def run(self,run,svc,cam,vision,params,grip_result,robot_params):
        with self.lock:
            cutoff=self.invalidated_at
            self.state={'phase':'checking','verified':False};self.answer=None;self.event.clear()
        try:
            if params.get('operator_confirmed') is not True or params.get('cell_clear') is not True:
                raise TransferError('Fresh approval required: human at E-stop and vertical lift clear')
            lift=number(params.get('lift_mm',5),'verification lift')
            if not 2<=lift<=5:raise TransferError('Verification lift must be 2..5 mm')
            mid=number(params.get('marker_id'),'plate marker ID')
            if mid!=int(mid) or not 0<=mid<50:raise TransferError('Marker ID must be integer 0..49')
            dz=number(params.get('plate_center_dz_mm'),'calibrated marker-to-plate-center Z offset')
            if abs(dz)>100:raise TransferError('Plate Z offset outside +/-100 mm')
            if params.get('plate_calibration_confirmed') is not True:raise TransferError('Confirm rigid marker calibration and level plate assumption')
            if not grip_result or not grip_result.get('gripped') or not grip_result.get('ok'):
                raise TransferError('Run a confirmed Grip stage first')
            stamp=number(grip_result.get('confirmed_at'),'grip timestamp')
            if stamp<cutoff or not 0<=time.time()-stamp<=120:raise TransferError('Grip evidence expired or invalidated; repeat Grip')
            command=number(grip_result.get('stopped_at_command'),'last confirmed E1 command')
            guard=GuardedService(svc,run,robot_params);guard._preflight()
            initial_grip=self.grip(svc,command)
            before=self.observe(svc,cam,vision,int(mid),dz,'before')
            # GuardedService checks envelope, kinematics, readiness and arrival.
            start=before['tcp'];guard.move_cartesian(start['X'],start['Y'],start['Z']+lift,start['Rz'],speed=5)
            guard._preflight();self.grip(svc,command)
            after=self.observe(svc,cam,vision,int(mid),dz,'after')
            delta={k:after['plate'][k]-before['plate'][k] for k in ('X','Y','Z')}
            if abs(delta['Z']-lift)>1.5 or math.hypot(delta['X'],delta['Y'])>2 or abs(wrap(after['plate']['Rz']-before['plate']['Rz']))>2:
                raise TransferError('Vision does not show the plate following the verification lift')
            with self.lock:
                self.state=dict(phase='awaiting_visual',verified=False,token=uuid.uuid4().hex,before=before,after=after,measured_lift_mm=delta['Z'])
            run.say('Lift completed. Inspect BEFORE/AFTER images and the actual plate; confirm it lifted securely and remains level. No transfer will start.')
            deadline=time.monotonic()+120
            while not self.event.wait(.1):
                if run.stopped() or time.monotonic()>deadline:raise TransferError('Visual verification stopped or timed out; no further motion')
            guard._preflight()
            if self.answer is not True:raise TransferError('Operator rejected pickup; no further motion')
            fresh=self.observe(svc,cam,vision,int(mid),dz,'snapshot')
            ensure_arrival(fresh['tcp'],after['tcp']);ensure_arrival(fresh['plate'],after['plate'])
            joints=svc.joints() or {}
            joints={k:number(joints.get(k),'joint '+k) for k in ('J1','J2','J3','J4')}
            g=self.grip(svc,command);end=svc.pose_mm();ensure_arrival(end,fresh['tcp']);guard._preflight()
            if time.time()-fresh['observed_at']>10:raise TransferError('Snapshot acquisition too slow; state freshness unknown')
            p=fresh['plate'];tcp=fresh['tcp'];a=math.radians(tcp['Rz']);dx=p['X']-tcp['X'];dy=p['Y']-tcp['Y']
            relative={'x_mm':math.cos(a)*dx+math.sin(a)*dy-number(vision.W.CLAW_ARM[0],'claw X'),
                      'y_mm':-math.sin(a)*dx+math.cos(a)*dy-number(vision.W.CLAW_ARM[1],'claw Y'),
                      'z_mm':p['Z']-tcp['Z'],'yaw_deg':wrap(p['Rz']-tcp['Rz'])}
            snapshot=dict(schema='bioyond-post-grasp-v1',captured_at=time.time(),expires_at=time.time()+30,
                joints=joints,tcp_pose_mm_deg=tcp,e1=g,plate_world_mm_deg=p,plate_relative_to_gripper=relative,
                gripper_frame='Origin: calibrated claw XY center at TCP Z; orientation: TCP yaw. Not jaw-center Z calibration.',
                pose_assumption='Level rigid plate: roll/pitch not measured. XYZ+yaw only.',marker_id=int(mid),plate_center_dz_mm=dz,
                calibration_stamps=fresh['calibration_stamps'],image=fresh['image'],operator_visual_confirmed=True,
                initial_grip=initial_grip,measured_lift_mm=delta['Z'],not_a_motion_authorization=True)
            with self.lock:
                if run.stopped() or self.invalidated_at>cutoff:raise TransferError('Verification invalidated by a stop/state change')
                self.state=dict(phase='verified',verified=True,snapshot=snapshot)
            run.say('Pickup verified; fresh snapshot available. No transfer motion commanded.','good')
            return {'ok':True,'pickup_verified':True,'snapshot':snapshot}
        except Exception as ex:
            with self.lock:self.state=dict(phase='failed',verified=False,error=str(ex))
            run.say('Pickup NOT verified: '+str(ex),'err');run.state='error'
            return {'ok':False,'pickup_verified':False,'error':str(ex)}
