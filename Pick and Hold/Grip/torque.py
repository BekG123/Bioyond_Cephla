"""Gripper-only vendor torque-limit control after the existing Lua Descent.

No motion at import, no automatic startup/reset and no position-only fallback.
The legacy position_grip Runner name is retained for the existing UI/pipeline.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import secrets
import threading
import time
from uuid import uuid4

from researcher_teaching import TeachingError
from trajectory_queue import LuaTrajectory
from .position import PositionGrip

VERSION=240101
PROFILE=Path(__file__).with_name('torque_profile.json')
REASONS={1:'invalid or consumed grip request',2:'arm or other external axis moved',
         3:'gripper feedback unavailable',4:'claw exceeded its closing range',
         5:'configured contact torque was not reached',6:'claw did not settle'}


def read_profile(path=PROFILE):
    try:
        raw=Path(path).read_bytes();p=json.loads(raw.decode('utf-8-sig'))
        finite=lambda v:type(v) in (int,float) and math.isfinite(v) and abs(v)<100000
        limits=p.get('force_limits')
        if (p.get('schema')!=1 or p.get('reviewed') is not True
            or not isinstance(limits,list) or len(limits)!=6
            or not all(finite(v) and v>=0 for v in limits) or limits[0]<=0
            or not finite(p.get('contact_torque_abs')) or p['contact_torque_abs']<=0
            or type(p.get('closing_torque_sign')) not in (int,float) or p['closing_torque_sign'] not in (-1,1)
            or not isinstance(p.get('force_units'),str) or not p['force_units'].strip()
            or not isinstance(p.get('source'),str) or not p['source'].strip()
            or p.get('e1_floor_mm')!=3.8 or not finite(p.get('speed')) or not 0<p['speed']<=5):
            raise ValueError('incomplete or unreviewed profile')
        return p,hashlib.sha256(raw).hexdigest()
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        raise TeachingError('Torque Grip needs a vendor-reviewed force profile in Developer view. '
                            'Configure Pick and Hold/Grip/torque_profile.json before running.') from error


class LuaTorqueGrip:
    TIMEOUT=20.
    OBSERVE_SECONDS=5.
    POLL=.1

    def __init__(self,service):self.service=service

    def execute(self,run,receipt,profile,record,save):
        svc=self.service
        def locked():
            def healthy():
                if run.stopped():raise TeachingError('Grip stopped; no retry.')
                refusal=svc._preflight()
                if refusal:raise TeachingError(refusal)
                PositionGrip._pose_matches(svc.pose_mm(),receipt['pose_mm'])
            healthy()
            robot=svc.robot
            reply=robot.set_sys_var_i({0:24,1:1,2:0,3:0,4:6,5:0,6:0},reply_timeout=10)
            if reply!={'index':1,'value':VERSION}:
                raise TeachingError('Publish main_hostpoint_descent_grip_137.bin before Torque Grip; no closing command sent.')
            # Lua snapshots and preserves all six external positions in native
            # units. The host's passive feedback independently checks E1.
            initial_e1=PositionGrip._number(svc.external_axes().get('E1'))
            if not 27.98<=initial_e1<=28.05:raise TeachingError('Grip requires the open claw from Descent.')
            joints=svc.joints();pose=svc.pose_mm()
            header=([pose[k] for k in ('X','Y','Z','Rz')]
                    +[joints[k] for k in ('J1','J2','J3','J4')]
                    +[profile['e1_floor_mm'],profile['speed']]+profile['force_limits']
                    +[profile['contact_torque_abs'],profile['closing_torque_sign']])
            token=secrets.randbelow(1073741823)+1
            record.update(token=token,protocol=VERSION,header=header)
            save()
            robot.set_sys_para_f(dict(enumerate(header)))
            answer=robot.set_sys_var_i({0:24,1:1,2:token,3:0,4:1,5:0,6:0},reply_timeout=10)
            if answer!={'index':1,'value':1} or robot.get_sys_var_i([7,8,9])!={7:token,8:1,9:0}:
                raise TeachingError('Torque Grip preparation was not confirmed; no closing command sent.')
            healthy()
            if abs(svc.external_axes()['E1']-initial_e1)>.05:raise TeachingError('Claw moved before Grip.')
            done,outcome=threading.Event(),{}
            def dispatch():
                try:outcome['reply']=robot.set_sys_var_i({0:24,1:1,2:token,3:0,4:2,5:0,6:0},reply_timeout=self.TIMEOUT)
                except Exception as error:outcome['error']=error
                finally:done.set()
            worker=threading.Thread(target=dispatch,daemon=True,name='lua-grip-reply')
            began=False
            record['samples']=[]
            def sample():
                healthy()
                e=PositionGrip._number(svc.external_axes().get('E1'))
                if not profile['e1_floor_mm']-.05<=e<=initial_e1+.05:
                    raise TeachingError('Claw left the configured closing range.')
                values=robot.get_sys_var_i([7,8,9,10,11,12])
                if values[7]!=token:raise TeachingError('Grip transaction changed unexpectedly.')
                item=dict(at=time.time(),e1_mm=e,pose_mm=svc.pose_mm(),registers=values)
                record['samples'].append(item);save()
                run.audit('lua_grip_feedback',**item)
                if values[8]==-1:raise TeachingError(REASONS.get(values[9],'Controller rejected Torque Grip.'))
                return e,values
            try:
                run.audit('lua_grip_command',protocol=VERSION,token=token,profile=profile,pose_mm=pose)
                healthy();began=True;started=time.monotonic();worker.start()
                deadline=time.monotonic()+self.TIMEOUT
                while not done.wait(self.POLL):
                    sample()
                    if time.monotonic()>deadline:raise TeachingError('Torque Grip timed out; no retry.')
                if 'error' in outcome:raise outcome['error']
                e,values=sample()
                if outcome.get('reply')!={'index':1,'value':1} or values[8]!=5 or values[9]!=0:
                    raise TeachingError('Torque Grip completion was not confirmed.')
                controller_elapsed=time.monotonic()-started
                # Catch delayed faults like the previous one after position success.
                # No extra report job, closing command, or release is sent here.
                end=time.monotonic()+self.OBSERVE_SECONDS
                settled=e
                while time.monotonic()<end:
                    time.sleep(self.POLL);e,values=sample()
                    if abs(e-settled)>.05:raise TeachingError('Claw moved during post-grip observation.')
                result=dict(ok=True,executor='lua_torque_grip',e1_position=e,
                    e1_floor_mm=profile['e1_floor_mm'],e1_torque=values[11]/1000.,
                    controller_elapsed_s=controller_elapsed,
                    observation_seconds=self.OBSERVE_SECONDS,total_elapsed_s=time.monotonic()-started,
                    contact_detected=True,grasp_verified=False,gripped=False,awaiting_inspection=True)
                record['completion_reply']=outcome.get('reply')
                return result
            except Exception:
                if began:
                    LuaTrajectory(svc).stop_controller();worker.join(3)
                    if worker.is_alive():svc.trajectory_fault=True
                raise
        return svc._locked(locked)


class TorqueGrip(PositionGrip):
    """Reuse only receipt/readiness plumbing; replace position-only execution."""
    def __init__(self,folder,service,runner,profile_path=PROFILE):
        super().__init__(folder,service,runner)
        self.profile_path=Path(profile_path)
        self.message='After Descent, Grip closes with the configured torque limit, then waits for inspection.'

    def configuration_ready(self):
        read_profile(self.profile_path)

    def public(self,robot):
        state=super().public(robot)
        state.update(method='lua_torque_grip',target_e1_mm=None,e1_floor_mm=3.8,
                     force_profile_ready=False,force_profile_file=str(self.profile_path))
        try:
            profile,digest=read_profile(self.profile_path)
            state.update(force_profile_ready=True,force_profile_sha256=digest,speed=profile['speed'])
        except TeachingError as error:
            state.update(can_start=False,blocker=str(error))
        if robot.get('errors'):
            state.update(can_start=False,blocker='Controller fault. Check Developer view before continuing.',
                         message='Controller fault after or during Grip; inspect before continuing.')
        return state

    def completed_descent(self,result,pose):
        super().completed_descent(result,pose)
        try:profile,digest=read_profile(self.profile_path)
        except TeachingError:return
        with self.lock:
            self.receipt.update(force_profile=profile,force_profile_sha256=digest)
            self._save_receipt()

    def _ready(self,robot):
        super()._ready(robot)
        _,digest=read_profile(self.profile_path)
        if self.receipt.get('force_profile_sha256')!=digest:
            raise TeachingError('Torque profile changed since Descent. Run Descent with the reviewed profile before Grip.')

    def execute(self,run,receipt):
        record=dict(id=uuid4().hex,at=time.time(),method='lua_torque_grip',descent=deepcopy(receipt),
                    grasp_verified=False)
        path=self.folder/(record['id']+'.json')
        def save():
            self.folder.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
        try:
            profile,digest=read_profile(self.profile_path)
            # Lacry's direct execute also uses the same checked configuration.
            if receipt.get('force_profile_sha256')!=digest:
                raise TeachingError('Torque profile changed after confirmation; request a fresh Grip.')
            record.update(force_profile=profile,force_profile_sha256=digest);save()
            self.message='Closing with the configured torque limit. Keep hands clear.'
            result=LuaTorqueGrip(self.service()).execute(run,receipt,profile,record,save)
            if result.get('ok') is not True:raise TeachingError(result.get('error','Torque Grip refused.'))
            record.update(result);save()
            self.message='Grip contact detected. Inspect the hold before lifting.'
            run.audit('lua_grip_complete',record=record);run.say(self.message,'good')
            return dict(result,record=str(path))
        except Exception as error:
            record.update(ok=False,error=str(error))
            try:save()
            except (OSError,ValueError,TypeError):pass
            self.message='Grip stopped. Check Developer details before continuing.'
            run.state='error';run.say(str(error),'err')
            return dict(ok=False,error=str(error),gripped=False,grasp_verified=False)

    def stop(self):
        result=super().stop()
        result['message']='Stop requested; the monitored grip will stop the controller. Use the E-stop for an emergency.'
        return result
