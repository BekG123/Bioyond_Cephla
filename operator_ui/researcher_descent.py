"""Researcher action for the commissioned Lua descent after a fresh Align."""
from copy import deepcopy
import time

from autonomy import TransferError, ensure_arrival, alignment_plan, check_path
from researcher_teaching import TeachingError
from pick_and_hold.Descend.lua_executor import LuaDescent, make_plan
from pick_and_hold.Descend.correction import corrected_plan, apply_correction


class ResearcherDescent:
    def __init__(self, service, runner, params, band, prepare, on_complete=None):
        self.service, self.runner = service, runner
        self.params, self.band, self.prepare = params, band, prepare
        self.on_complete = on_complete
        self.message = 'Descend adjusts the claws above the plate, opens them, then lowers to the taught position.'

    def _plan(self, start, joints, target, cfg, envelope, band):
        if target.get('plate_profile_id'):
            from projected_pickup import descent_plan
            return descent_plan(start,joints,target,cfg,envelope,band)
        return corrected_plan(start,joints,target,cfg,envelope,band)

    def _target(self, run):
        if run.name=='projected_alignment':
            from projected_pickup import target
            value = target()
            digest = (run.result or {}).get('profile_sha256')
            if digest and digest != value['plate_profile_sha256']:
                raise TransferError('48-well profile changed after alignment. Recalibrate before descent.')
            return value
        return deepcopy(run.target or {})

    def preview_after_alignment(self, target):
        """Check the complete future path without moving or forging an Align receipt."""
        svc = self.service()
        if not svc.envelope_enabled:
            raise TransferError('The descent workspace must be enabled.')
        pose, joints, cfg = svc.pose_mm(), svc.joints(), self.params()
        legs = alignment_plan(pose, target, joints, cfg, svc.envelope,
                              max(300, pose['Z']), validate_descent=False)
        for point in legs:
            joints = check_path(pose, point, joints, cfg, svc.envelope)
            pose = dict(point)
        return self._plan(pose, joints, target, cfg, svc.envelope, self.band())

    def public(self, robot):
        run = self.runner()
        active = run.active and run.name == 'researcher_descend'
        blocker = ''
        if not robot.get('connected') or not robot.get('ok'):
            blocker = 'Robot disconnected. Connect the robot first.'
        elif robot.get('errors'):
            blocker = 'Robot needs attention. Check Developer view.'
        elif run.active:
            blocker = 'Wait for the current action to finish.'
        elif run.name not in ('align', 'researcher_align', 'projected_alignment') or run.state != 'done' or not (run.result or {}).get('ok'):
            blocker = 'Run Align before Descend.'
        elif time.time()-run._t0 > 600:
            blocker = 'Alignment has expired. Run Align again.'
        else:
            try:
                svc = self.service()
                if not svc.envelope_enabled:
                    raise TransferError('workspace')
                self._plan(robot['pose_mm'], robot['joints'], self._target(run),
                          self.params(), svc.envelope, self.band())
            except TransferError as error:
                blocker = str(error)
            except Exception:
                blocker = 'Descent path needs checking. Run Align again or check Developer view.'
        message = self.message
        if active and run.log:
            phase = run.log[-1]['msg']
            if 'fast approach' in phase: message = 'Approaching the plate.'
            elif 'torque baseline' in phase: message = 'Checking contact sensors.'
            elif 'slow probing' in phase: message = 'Lowering carefully to the plate.'
        return dict(active=active, can_start=not blocker, blocker=blocker, message=message)

    def start(self, body):
        if body.get('ready') is not True:
            raise TeachingError('Confirm the empty claw, clear path and supervised E-stop before Descend.', 400)
        svc, run = self.service(), self.runner()
        status = self.public(svc.status())
        if not status['can_start']:
            raise TeachingError(status['blocker'])
        target, start = self._target(run), svc.pose_mm()
        plan=self._plan(start,svc.joints(),target,self.params(),svc.envelope,self.band())
        self.message = 'Adjusting the claws above the plate, then opening and descending. Keep hands clear.'
        result = run.start('researcher_descend', self.execute, svc, target, start,plan)
        if not result.get('ok'):
            raise TeachingError('Another robot action is running.')
        return dict(ok=True, message=self.message)

    def execute(self, run, svc, target, start, plan=None):
        from sequences import _abort
        try:
            self.prepare(run, svc)
            if run.stopped():
                raise TransferError('Stopped before opening the claw.')
            ensure_arrival(svc.pose_mm(), start)
            cfg = self.params()
            current_plan=self._plan(svc.pose_mm(),svc.joints(),target,cfg,svc.envelope,self.band())
            if plan and current_plan['profile_sha256']!=plan['profile_sha256']:
                raise TransferError('Descent correction changed after Start; no motion sent.')
            plan=current_plan
            apply_correction(run,svc,plan,cfg)
            target=plan['target']
            run.target=deepcopy(target)
            make_plan(svc.pose_mm(), svc.joints(), target, cfg, svc.envelope, self.band())
            maximum = cfg['claw_gap_max_mm']-cfg['claw_gap_min_mm']
            result = svc.move_gripper(maximum, speed=5)
            report = result.get('gripper') or {}
            if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
                raise TransferError('Claw opening was not confirmed; no descent.')
            opening = report.get('e1_position')
            if type(opening) not in (int,float) or not maximum-.02 <= opening <= maximum+.05:
                raise TransferError('Claw did not open fully; no descent.')
            run.audit('researcher_descent_claw_open', result=result)
            if run.stopped():
                raise TransferError('Stopped after opening the claw; no descent.')
            ensure_arrival(svc.pose_mm(), plan['hover'])
            result = LuaDescent(svc).execute(run, target, cfg, self.band())
            if not result.get('ok'):
                raise TransferError(result.get('error','Descent did not complete.'))
            result=dict(result,descent_correction=plan)
            if target.get('plate_profile_id'):
                result.update(plate_profile_id=target['plate_profile_id'],
                              open_claw_trial=target.get('open_claw_trial') is True,
                              gripping_height_acceptance_pending=target.get('open_claw_trial') is True)
            if self.on_complete and not result.get('open_claw_trial'):
                self.on_complete(result, svc.pose_mm())
            self.message = 'Descent complete. The claw remains open.'
            return result
        except Exception as error:
            self.message = 'Descent stopped. Check Developer view before trying again.'
            return _abort(run, str(error))

    def stop(self):
        run = self.runner()
        if not run.active or run.name != 'researcher_descend':
            raise TeachingError('No researcher descent is running.')
        run.request_stop()
        self.message = 'Stop requested. Keep hands clear until movement has stopped.'
        return dict(ok=True, message=self.message)
