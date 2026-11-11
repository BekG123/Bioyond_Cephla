"""Post-grip 5 mm slow lift followed by the shared Lacry IK Home entry point."""
from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

from autonomy import TransferError, check_path
from loaded_home_trial import near
from scope_compact137 import HoldingService
from trajectory_queue import LuaTrajectory, prepare_points
from researcher_teaching import TeachingError


class PickupHome:
    def __init__(self, connection, folder, plate_profile=False):
        self.connection = connection
        self.home = connection.home
        self.folder = Path(folder)
        self.lift_receipt = None
        self.home_attempt = None
        self.plate_profile = plate_profile
        self.grip_mm = 3.9 if plate_profile else 3.7

    def configuration_ready(self):
        from pick_and_hold.Grip.reference_grip import configuration
        from pick_and_hold.Grip.fast_position_plan import plan_closure
        configuration()
        if self.plate_profile:
            from projected_pickup import load, accepted_grip
            if not accepted_grip(load()[0]):
                raise TeachingError('Accepted 48-well grip evidence is required before lift/Home.')
        elif plan_closure(28)['target_e1_mm'] != 3.7:
            raise TeachingError('Pickup Home requires the accepted 3.7 mm grip.')
        self.connection.history()
        self.home.target()

    def start_lift(self, grip_result):
        self.configuration_ready()
        if (grip_result.get('ok') is not True or grip_result.get('target_e1_mm') != self.grip_mm
                or grip_result.get('executor') != 'staged_reference_position'):
            raise TeachingError('Successful current Grip is required before pickup lift.')
        service,run = self.home.get_service(),self.home.get_runner()
        if not run.owns_reservation:
            raise TeachingError('The confirmed pickup workflow must own the lift.')
        # Verify the full existing Home corridor before beginning the 5 mm lift.
        context = self.connection.propose()
        if not context['preserve_gripper'] or abs(context['e1']-self.grip_mm) > .05:
            raise TeachingError('Keep the accepted grip and running Auto state; no startup is allowed.')
        source = Path(grip_result['record'])
        grip = json.loads(source.read_bytes())
        if not grip.get('ok') or grip.get('target_e1_mm') != self.grip_mm or not 0 <= time.time()-grip['at'] <= 600:
            raise TeachingError('Current grip evidence is unavailable or stale.')
        near(context['start'],grip['pose_mm'])
        target = {**context['start'],'Z':context['start']['Z']+5}
        points,_ = prepare_points(context['start'],context['joints'],[target],context['cfg'],
                                   reviewed=True,home_transit=True)
        check_path(context['start'],points[0],context['joints'],context['cfg'],context['envelope'])
        self.lift_receipt = None
        self.home_attempt = None
        return run.start('pickup_slow_lift',self.execute_lift,context,points[0],str(source))

    def execute_lift(self, run, context, target, grip_record):
        service = self.home.get_service()
        guarded = HoldingService(service,self.grip_mm,context['envelope'])
        record = dict(at=time.time(),start=context['start'],target=target,speed=5,
                      grip_record=grip_record,home_context=context,samples=[],
                      grasp_verified=False,status='started')
        self.folder.mkdir(parents=True,exist_ok=True)
        path=self.folder/(uuid4().hex+'.json')
        def save():
            path.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
        save()
        try:
            near(service.pose_mm(),context['start'])
            if self.home.params() != context['cfg']:
                raise TransferError('Motion settings changed before pickup lift.')
            self.home.require_home_queue(LuaTrajectory(guarded).capability())
            def progress(phase,done,total):
                record['samples'].append(dict(at=time.time(),phase=phase,progress=done,
                    pose_mm=service.pose_mm(),e1_mm=service.external_axes()['E1']))
                run.say(f'Lift 5 mm: {phase} {done:.0f}/{total}.')
            result=LuaTrajectory(guarded).execute(run,service.pose_mm(),service.joints(),
                [target],context['cfg'],5,progress,reviewed=True,home_transit=True)
            if result.get('ok') is not True:
                raise TransferError('Pickup lift did not finish; Home will not start.')
            near(service.pose_mm(),target,.05)
            record.update(status='completed',result=result,finished_at=time.time(),final=service.status())
            self.lift_receipt=dict(target=target,context=context,record=str(path),finished_at=time.time())
            return dict(ok=True,record=str(path),target=target,grasp_verified=False)
        except Exception as error:
            record.update(status='failed_or_uncertain',error=str(error))
            raise
        finally:
            save()
            run.audit('pickup_slow_lift',record=record)

    def start_home(self, lift_result):
        receipt=self.lift_receipt
        if (not receipt or lift_result.get('ok') is not True
                or lift_result.get('record') != receipt['record']
                or not 0 <= time.time()-receipt['finished_at'] <= 30):
            raise TeachingError('Fresh successful pickup lift is required before Home.')
        near(self.home.get_service().pose_mm(),receipt['target'])
        plan=self.connection.propose()
        for key in ('cfg','envelope','home','target_id','points_sha256'):
            if plan[key] != receipt['context'][key]:
                raise TeachingError('Home settings changed during pickup; no Home move started.')
        if not plan['preserve_gripper'] or abs(plan['e1']-self.grip_mm) > .05:
            raise TeachingError('Grip/controller state changed; no Home move started.')
        plan.update(id='pickup-home-'+uuid4().hex,
                    authorization_scope='Confirmed Full Calibration includes slow lift and loaded Home.')
        self.lift_receipt=None
        result,self.home_attempt=self.connection.start(plan)
        return result

    def finish_home(self, sequence):
        if self.home_attempt:
            self.connection.finish(self.home_attempt,deepcopy(sequence))
            self.home_attempt=None
