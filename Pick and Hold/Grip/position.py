"""One position command after a successful descent; no force-based search."""
from copy import deepcopy
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4
from researcher_teaching import TeachingError


class PositionGrip:
    TARGET = 3.8
    SPEED = 5
    MAX_AGE = 600
    SETTLE_TIMEOUT = 2.0
    SETTLE_INTERVAL = .1
    SETTLE_SAMPLES = 3
    POSITION_TOLERANCE = .05

    def __init__(self, folder, service, runner):
        self.folder = Path(folder)
        self.service, self.runner = service, runner
        self.lock = threading.RLock()
        self.receipt = None
        self.message = 'After Descent, Grip closes once to the tested 3.8 mm setting.'
        try:
            data = json.loads((self.folder/'descent_ready.json').read_text(encoding='utf-8-sig'))
            if not isinstance(data,dict):raise ValueError('Invalid descent receipt')
            if data.get('available') is True:
                self.receipt = data
        except (OSError, ValueError):
            pass

    def _save_receipt(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        temp = self.folder/'descent_ready.tmp'
        temp.write_text(json.dumps(self.receipt, indent=2, allow_nan=False), encoding='utf-8')
        temp.replace(self.folder/'descent_ready.json')

    def completed_descent(self, result, pose):
        if not result.get('ok') or result.get('breach') or result.get('executor')!='lua_descent':
            raise TeachingError('Only a successful Lua descent can prepare Grip.')
        self._pose_matches(pose, pose)
        with self.lock:
            self.receipt = dict(id=uuid4().hex, available=True, recorded_at=time.time(),
                                pose_mm=deepcopy(pose), descent_result=deepcopy(result))
            self._save_receipt()

    def invalidate(self):
        with self.lock:
            if self.receipt and self.receipt.get('available'):
                self.receipt['available'] = False
                self._save_receipt()

    @staticmethod
    def _number(value):
        if type(value) not in (float,int) or not math.isfinite(value):
            raise TeachingError('Robot position feedback is unavailable.')
        return value

    @classmethod
    def _pose_matches(cls, current, expected):
        for key in ('X','Y','Z','Rz'):
            delta = cls._number(current.get(key))-cls._number(expected.get(key))
            if key=='Rz': delta=(delta+180)%360-180
            if abs(delta)>.05:
                raise TeachingError('Arm moved since Descent. Align and descend again before Grip.')

    def _ready(self, robot):
        receipt = self.receipt
        if not receipt or not receipt.get('available'):
            raise TeachingError('Complete Descent before Grip.')
        age=time.time()-self._number(receipt.get('recorded_at'))
        if not 0<=age<=self.MAX_AGE:
            raise TeachingError('Descent readiness expired. Align and descend again.')
        result=receipt.get('descent_result',{})
        if not result.get('ok') or result.get('breach') or result.get('executor')!='lua_descent':
            raise TeachingError('Successful descent record is unavailable.')
        if not robot.get('connected') or not robot.get('ok') or robot.get('errors'):
            raise TeachingError('Robot disconnected or needs attention. Check Developer view.')
        if robot.get('control_mode',{}).get('mode')!='auto' or not robot.get('enabled') or robot.get('program_state',{}).get('state')!='running':
            raise TeachingError('Keep Auto ready after Descent. Grip never starts or resets the controller program.')
        self._pose_matches(robot.get('pose_mm',{}), receipt['pose_mm'])
        e1=self._number(robot.get('external_axes',{}).get('E1'))
        if not 27.98<=e1<=28.05:
            raise TeachingError('Claw is no longer fully open after Descent. Inspect before continuing.')

    def public(self, robot):
        with self.lock:
            run=self.runner()
            active=run.active and run.name=='position_grip'
            blocker=''
            try:
                if run.active:raise TeachingError('Wait for the current action to finish.')
                self._ready(robot)
            except (TeachingError,KeyError,TypeError,ValueError) as error:
                blocker=str(error)
            return dict(active=active,can_start=not blocker,blocker=blocker,message=self.message,
                        descent_id=(self.receipt or {}).get('id'),target_e1_mm=self.TARGET,
                        speed=self.SPEED,grasp_verified=False)

    def start(self, body):
        with self.lock:
            if body.get('ready') is not True:
                raise TeachingError('Confirm plate supported and centered, hands clear, and E-stop supervised.',400)
            if set(body)-{'ready','descent_id'}:
                raise TeachingError('Grip uses the saved plate setting; arbitrary motion parameters are not accepted.',400)
            if self.runner().active:raise TeachingError('Another action is running.')
            self._ready(self.service().status())
            if body.get('descent_id')!=self.receipt['id']:
                raise TeachingError('Grip request is stale. Refresh before continuing.')
            receipt=deepcopy(self.receipt)
            # Consume before dispatch, including failed/uncertain attempts and restarts.
            self.invalidate()
            result=self.runner().start('position_grip',self.execute,receipt)
            if not result.get('ok'):raise TeachingError('Another action owns the robot.')
            return dict(ok=True,message='Closing to the plate setting. Keep hands clear.')

    def execute(self, run, receipt):
        svc=self.service()
        record=dict(id=uuid4().hex,at=time.time(),descent=receipt,target_e1_mm=self.TARGET,
                    speed=self.SPEED,grasp_verified=False)
        path=self.folder/(record['id']+'.json')
        def save():
            self.folder.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
        def check():
            if run.stopped():raise TeachingError('Grip stopped; no further command sent.')
            refusal=svc._preflight()
            if refusal:raise TeachingError(refusal)
            self._pose_matches(svc.pose_mm(),receipt['pose_mm'])
        try:
            check()
            e1=self._number(svc.external_axes().get('E1'))
            if not 27.98<=e1<=28.05:raise TeachingError('Claw moved before Grip.')
            record['before_e1_mm']=e1
            save()  # Logging failure prevents dispatch.
            check()
            self.message='Closing once to the plate setting. Keep hands clear.'
            run.audit('position_grip_command',target_e1_mm=self.TARGET,speed=self.SPEED,descent_id=receipt['id'])
            response=svc.move_gripper(self.TARGET,speed=self.SPEED)
            record['response']=response
            save()
            if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
                raise TeachingError('Grip completion was not confirmed. Inspect before any further action.')
            actual=self._number(response.get('gripper',{}).get('e1_position'))
            record['immediate_report_e1_mm']=actual
            check()
            # The Lua completion report may precede final E1 settling. Verify
            # fresh native feedback; never resend the close command or widen
            # the position tolerance to make a stalled closure pass.
            record['settling_samples']=[]
            began=time.monotonic();deadline=began+self.SETTLE_TIMEOUT;stable=0
            while True:
                check()
                settled=self._number(svc.external_axes().get('E1'))
                now=time.monotonic()
                record['settling_samples'].append(dict(elapsed_s=now-began,e1_mm=settled))
                save()
                if now>deadline:
                    raise TeachingError('Claw did not settle at the setting. Inspect the plate; no automatic retry or release.')
                stable=stable+1 if abs(settled-self.TARGET)<=self.POSITION_TOLERANCE else 0
                if stable>=self.SETTLE_SAMPLES:
                    break
                time.sleep(self.SETTLE_INTERVAL)
            check()
            self.message='Grip complete. Claw settled at the tested 3.8 mm setting.'
            record.update(ok=True,measured_e1_mm=settled,pose_mm=svc.pose_mm())
            save()
            run.audit('position_grip_complete',record=record)
            run.say(self.message,'good')
            return dict(ok=True,gripped=False,grasp_verified=False,awaiting_inspection=True,
                        e1_position=settled,target_e1_mm=self.TARGET,record=str(path))
        except Exception as error:
            self.message='Grip stopped. Inspect Developer details before continuing.'
            record.update(ok=False,error=str(error))
            try:save()
            except (OSError,ValueError,TypeError):pass
            run.state='error';run.say(str(error),'err')
            return dict(ok=False,error=str(error),gripped=False,grasp_verified=False)

    def stop(self):
        run=self.runner()
        if not run.active or run.name!='position_grip':raise TeachingError('No Grip action is running.')
        run.request_stop()
        return dict(ok=True,message='Stop requested. The current closing move may finish; use the physical E-stop for an emergency.')
