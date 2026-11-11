"""Post-grip proof lift, reseating, release and empty clearance at HOME.

No IDLE travel, holder rotation, program startup or recovery. Each phase is
bound to its predecessor's successful receipt and the original gripping pose.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

from autonomy import TransferError, check_path
from calibration_e2 import verify as verify_e2
from loaded_home_trial import near
from researcher_teaching import TeachingError
from scope_compact137 import HoldingService
from trajectory_queue import LuaTrajectory


class PickupHolder:
    completion_action = 'Clearance'
    completion_message = 'Full calibration complete. The plate is in the HOME holder; the open arm is 30 mm above it. Holder rotation is the next experiment step.'
    steps = (
        ('Lift','pickup_slow_lift','Lift the plate 5 mm'),
        ('Reseat','pickup_holder_reseat','Lower the plate back into HOME'),
        ('Release','pickup_holder_release','Release the plate at HOME'),
        ('Clearance','pickup_holder_clearance','Raise the empty arm 30 mm'),
    )

    def __init__(self, home, folder):
        self.home, self.folder = home, Path(folder)
        self.receipt = None
        self.context = None

    def configuration_ready(self):
        from plate48_workflow import reference
        try:
            reference()  # Preserve current descent/grip evidence requirements.
        except (TransferError, OSError, ValueError, KeyError) as error:
            raise TeachingError(str(error)) from error

    def _state(self, e1):
        svc = self.home.get_service()
        r = svc.status()
        if (not r.get('ok') or not r.get('connected') or r.get('errors')
                or not r.get('enabled') or r.get('control_mode',{}).get('mode') != 'auto'
                or r.get('program_state',{}).get('state') != 'running'):
            raise TeachingError('Healthy running Auto required; no automatic startup.')
        guard = HoldingService(svc, e1, self.context['envelope'])
        refusal = guard._preflight()
        if refusal: raise TeachingError(refusal)
        if self.home.params() != self.context['cfg']:
            raise TeachingError('Motion settings changed during HOME exchange.')
        return svc, guard

    def start_lift(self, result):
        self.configuration_ready()
        run = self.home.get_runner()
        if not run.owns_reservation: raise TeachingError('Full calibration must own the arm.')
        self.receipt = None
        if (result.get('ok') is not True or result.get('target_e1_mm') != 3.9
                or result.get('executor') != 'staged_reference_position'):
            raise TeachingError('Fresh successful 3.9 mm grip required.')
        raw = Path(result['record']).read_bytes(); grip = json.loads(raw)
        if (grip.get('ok') is not True or grip.get('target_e1_mm') != 3.9
                or not 0 <= time.time()-grip['at'] <= 600):
            raise TeachingError('Grip evidence is unavailable or stale.')
        svc = self.home.get_service()
        start = deepcopy(svc.pose_mm()); near(start, grip['pose_mm'], .05)
        self.context = dict(start=start, cfg=deepcopy(self.home.params()),
                            envelope={k:list(v) for k,v in svc.envelope.items()},
                            grip_record=result['record'], grip_sha256=hashlib.sha256(raw).hexdigest())
        svc, _ = self._state(3.9)
        # Preflight the complete vertical corridor before the first lift.
        q = svc.joints(); previous = start
        for target in (dict(start,Z=start['Z']+5), start, dict(start,Z=start['Z']+30)):
            q = check_path(previous,target,q,self.context['cfg'],self.context['envelope'])
            previous = target
        verify_e2(svc, run, correct=False)
        return run.start('pickup_slow_lift',self.execute,'Lift',dict(start,Z=start['Z']+5),5,3.9)

    def _next(self, action, previous, expected, target, speed, e1):
        run = self.home.get_runner(); receipt = self.receipt
        if (not run.owns_reservation or not receipt or receipt['action'] != expected
                or previous.get('ok') is not True or previous.get('record') != receipt['record']
                or not 0 <= time.time()-receipt['at'] <= 30):
            raise TeachingError('Fresh successful '+expected+' required before '+action+'.')
        svc, _ = self._state(e1); near(svc.pose_mm(),receipt['pose'],.05)
        self.configuration_ready()
        verify_e2(svc, run, correct=False)
        if hashlib.sha256(Path(self.context['grip_record']).read_bytes()).hexdigest() != self.context['grip_sha256']:
            raise TeachingError('Grip evidence changed during HOME exchange.')
        self.receipt = None  # Consume before dispatch; never replay an uncertain phase.
        job = dict(Reseat='pickup_holder_reseat',Release='pickup_holder_release',Clearance='pickup_holder_clearance')[action]
        return run.start(job,self.execute,action,target,speed,e1)

    def start_reseat(self, result):
        return self._next('Reseat',result,'Lift',self.context['start'],5,3.9)

    def start_release(self, result):
        return self._next('Release',result,'Reseat',self.context['start'],5,3.9)

    def start_clearance(self, result):
        start=self.context['start']
        return self._next('Clearance',result,'Release',dict(start,Z=start['Z']+30),137,28)

    def execute(self, run, action, target, speed, e1):
        self.folder.mkdir(parents=True,exist_ok=True)
        path=self.folder/(uuid4().hex+'.json')
        record=dict(at=time.time(),action=action,target=target,speed=speed,context=self.context,
                    status='started',samples=[],holder_rotation_sent=False,idle_travel_sent=False)
        def save(): path.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
        save()
        svc = self.home.get_service()
        try:
            if run.stopped(): raise TransferError('Stopped before '+action)
            svc, guard = self._state(e1)
            if action == 'Release':
                near(svc.pose_mm(),self.context['start'],.05)
                result=svc.move_gripper(28,5)
                if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
                    raise TransferError('Release uncertain; no ascent.')
                self._state(28)
            else:
                check_path(svc.pose_mm(),target,svc.joints(),self.context['cfg'],self.context['envelope'])
                self.home.require_home_queue(LuaTrajectory(guard).capability())
                def progress(phase,done,total):
                    record['samples'].append(dict(at=time.time(),phase=phase,progress=done,
                        pose_mm=svc.pose_mm(),e1_mm=svc.external_axes()['E1']))
                    run.say(f'{action}: {phase} {done:.0f}/{total}.')
                result=LuaTrajectory(guard).execute(run,svc.pose_mm(),svc.joints(),[target],
                    self.context['cfg'],speed,progress,reviewed=True,home_transit=True,home_speed137=True)
                if result.get('ok') is not True or result.get('recovered'):
                    raise TransferError(action+' did not verify; no next phase.')
                self._state(e1)
            near(svc.pose_mm(),target,.05)
            if run.stopped(): raise TransferError('Stopped during '+action)
            record.update(status='completed',result=result,final=svc.status(),finished_at=time.time())
            self.receipt=dict(action=action,record=str(path),pose=deepcopy(svc.pose_mm()),at=time.time())
            return dict(ok=True,record=str(path),pose_mm=svc.pose_mm(),
                        payload='empty' if action in ('Release','Clearance') else 'held',
                        station='HOME',grasp_verified=False)
        except Exception as error:
            self.receipt=None; record.update(status='failed_or_uncertain',error=str(error))
            try: record['stop_response']=svc.program('stop')
            except Exception as stop_error: record['stop_error']=str(stop_error)
            raise
        finally:
            save(); run.audit('pickup_holder_phase',record=record)
