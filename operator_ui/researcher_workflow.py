"""Researcher-triggered calibration/alignment, with durable teaching provenance.

Descend and Grip are ONLY recorded by StationTeaching after manual operation.
No automatic descent, grip, Hamilton move, or replay is dispatched here.
"""
from copy import deepcopy
import logging
import time

from researcher_teaching import PLATE_WORKFLOW, PLATE_LIMITATIONS, TeachingError, next_station, utc_now, numbers


class PlateTeaching:
    def __init__(self, teaching, get_runner, get_camera, get_draggo, calibrate, align, calibration_logs=None):
        self.teaching = teaching
        self.get_runner, self.get_camera, self.get_draggo = get_runner, get_camera, get_draggo
        self.calibrate, self.align = calibrate, align
        self.context = None
        self.message = ''
        self.active_step = None
        self.guidance = None
        self.calibration_logs = calibration_logs

    def publish_guidance(self, guidance):
        self.guidance = deepcopy(guidance)
        self.message = guidance['message']

    def invalidate(self):
        self.context = None

    def public(self):
        run = self.get_runner()
        with self.teaching.lock:
            draft = self.teaching._load().get('draft')
            available = bool(draft and draft.get('workflow') == PLATE_WORKFLOW and
                             any(p['station'] == 'Home' for p in draft['waypoints']))
            current = bool(available and self._current_calibration(draft))
        return dict(active=bool(run.active and self.active_step), step=self.active_step,
                    message=self.message or 'Run calibration and alignment separately. Record Descend and Grip after performing them manually.',
                    can_stop=bool(run.active and self.active_step), guidance=self.guidance,
                    can_calibrate=available and not run.active, can_align=current and not run.active,
                    setup_message='Capture Home in a plate teaching draft first.' if not available else
                        'Calibrate is available again. Run it to create a fresh target for Align.' if not current else
                        'Calibrate or Align can run again. Earlier records are preserved in draft history; later steps must be recorded again.')

    def _current_calibration(self, draft):
        event = next((p for p in reversed(draft['waypoints']) if p['station'] == 'Calibrate'), None)
        return (event and self.context and self.context['draft_id'] == draft['id'] and
                self.context['captured_at'] == event['captured_at'] and time.monotonic()-self.context['time'] <= 600)

    def adopt(self, body):
        with self.teaching.lock:
            data = self.teaching._load()
            draft = self.teaching._draft(data, body)
            if any(p['station'] != 'Home' for p in draft['waypoints']):
                raise TeachingError('Start a new draft for the plate workflow; this draft already has later positions.')
            draft['workflow'] = PLATE_WORKFLOW.copy()
            draft['capture_kind'] = 'positions_and_observed_actions'
            draft['limitations'] = PLATE_LIMITATIONS.copy()
            draft['revision'] += 1
            self.teaching._store(data)
        return dict(ok=True, **self.teaching.public())

    def stop(self):
        if not self.active_step or not self.get_runner().active:
            raise TeachingError('No researcher automatic step is running.')
        self.message = 'Stop requested. The current movement finishes before the sequence stops. Use the physical E-stop for an emergency.'
        return self.get_runner().request_stop()

    def start(self, action, body):
        if action not in ('Calibrate', 'Align'):
            raise TeachingError('Only calibration and alignment can run automatically here.', 400)
        if body.get('ready') is not True:
            raise TeachingError('Confirm hands are clear, the gripper is empty, the area is clear, and the E-stop is supervised.', 400)
        with self.teaching.lock:
            draft = self.teaching._draft(self.teaching._load(), body)
            if (draft.get('workflow') != PLATE_WORKFLOW or
                    not any(p['station'] == 'Home' for p in draft['waypoints'])):
                raise TeachingError('Capture Home in a plate teaching draft first.')
            if action == 'Align' and not self._current_calibration(draft):
                raise TeachingError('Run Calibrate first to create a fresh alignment target. Earlier records will be preserved.')
            ident, revision = draft['id'], draft['revision']
        service = self.teaching.get_service()
        state = service.status()
        if not state.get('connected') or not state.get('ok') or state.get('errors'):
            raise TeachingError('Robot disconnected or needs attention. Resolve that before running an automatic step.')
        if self.get_runner().active:
            raise TeachingError('Another robot task is running.')
        self.guidance = None
        self.message = ('Preparing automatic Wide calibration. Keep hands clear.' if action == 'Calibrate' else 'Align is running. Keep hands clear.')
        self.active_step = action
        result = self.get_runner().start('researcher_' + action.lower(), self._execute, action, ident, revision)
        if not result.get('ok'):
            self.active_step = None
            raise TeachingError('Another robot task is running.')
        return dict(ok=True, message=self.message)

    @staticmethod
    def _checked(result):
        if not result.get('ok') or result.get('recovered'):
            if (result.get('code') == 'gripper_held_start_refused'
                    and result.get('program_start_sent') is False):
                from home_attempts import ProgramStartRefused
                raise ProgramStartRefused(result.get('error', 'Program startup refused'))
            raise RuntimeError(result.get('error', 'Controller action did not complete'))

    def _prepare(self, run, service):
        # Called only from an explicit Calibrate/Align/Home/Claw click with hands-clear/empty
        # confirmation. Never executed by polling, capture, or page loading.
        def check():
            if run.stopped():
                raise RuntimeError('Stopped before next controller action')
        def status():
            check()
            state = service.status()
            if (not state.get('connected') or not state.get('ok') or state.get('errors')
                    or state.get('control_mode', {}).get('mode') not in ('manual', 'auto')
                    or not isinstance(state.get('enabled'), bool)):
                raise RuntimeError('Controller readiness is unavailable or has an active alert; no further preparation commands sent')
            return state

        def verified(label, predicate):
            deadline = time.monotonic() + 4
            while True:
                state = status()
                if predicate(state):
                    trace = getattr(run, 'calibration_trace', None)
                    if trace:
                        trace.record('controller_verified', phase=label, mode=state['control_mode']['mode'],
                                     enabled=state['enabled'], program=state['program_state']['state'])
                    return state
                if time.monotonic() >= deadline:
                    raise RuntimeError(f'Controller did not confirm {label}; no further preparation commands sent')
                time.sleep(.1)
        check()
        hand = self.get_draggo().public(status())
        if hand['blocked']:
            self._checked(self.get_draggo().change(False))
        elif hand['state'] not in ('off',):
            raise RuntimeError('Hand-guiding state is unavailable')
        check()
        state = status()
        if (state.get('control_mode', {}).get('mode') == 'auto' and state.get('enabled')
                and state.get('program_state', {}).get('state') == 'running'):
            refusal = service._preflight()
            if refusal:
                raise RuntimeError(refusal)
            return  # Already prepared: do not restart Lua or reset the jaws.
        if state['program_state']['state'] != 'stopped':
            self._checked(service.program('stop'))
            state = verified('program stopped', lambda s: s['program_state']['state'] == 'stopped')
        # remoteDisable is Auto-only. DragGo exit already disabled the arm;
        # never send a redundant remoteDisable while the controller is Manual.
        if state['enabled']:
            if state['control_mode']['mode'] == 'manual':
                self._checked(self.get_draggo().change(False))  # native Manual disable
            else:
                self._checked(service.set_enable(False, True))
        state = verified('servos disabled', lambda s: not s['enabled'])
        if state['control_mode']['mode'] != 'auto':
            self._checked(service.switch_mode('auto'))
        verified('Auto mode with servos disabled', lambda s: s['control_mode']['mode'] == 'auto' and not s['enabled'])
        self._checked(service.set_enable(True, True))
        verified('Auto mode with servos enabled', lambda s: s['control_mode']['mode'] == 'auto' and s['enabled'])
        # Existing program startup resets the empty jaws: disclosed in UI.
        self._checked(service.program('start'))
        verified('controller program running', lambda s: s['program_state']['state'] == 'running')
        refusal = service._preflight()
        if refusal:
            raise RuntimeError(refusal)

    def _execute(self, run, action, ident, revision):
        service = self.teaching.get_service()
        trace = None
        try:
            if run.stopped():
                raise RuntimeError('Stopped before ' + action.lower())
            if action == 'Align':
                from pick_and_hold.Calibration.fast_disk import ensure_arrival
                ensure_arrival(service.pose_mm(), self.context['pose'])
            # A repeat invalidates subsequent steps, but never erases evidence.
            # Persist the old attempt before issuing any controller commands.
            with self.teaching.lock:
                data = self.teaching._load()
                draft = self.teaching._draft(data, dict(draft_id=ident, revision=revision))
                cut = next((i for i,p in enumerate(draft['waypoints']) if p['station'] == action), None)
                if cut is not None:
                    draft.setdefault('history', []).append(dict(archived_at=utc_now(),
                        reason='Repeat ' + action, revision=revision, waypoints=deepcopy(draft['waypoints'])))
                    draft['waypoints'] = draft['waypoints'][:cut]
                    draft['reviewed'] = False
                    draft['revision'] += 1
                    self.teaching._store(data)
                    revision = draft['revision']
            if action == 'Calibrate':
                self.context = None
                if run.stopped():
                    raise RuntimeError('Stopped before calibration')
                if self.calibration_logs:
                    from pick_and_hold.Calibration.fast_disk import CalibrationTrace
                    trace = CalibrationTrace(self.calibration_logs, 'automatic', 'Wide')
                    trace.record('setup', draft_id=ident, revision=revision)
                run.calibration_trace = trace
                camera = self.get_camera()
                if not camera.info().get('enabled'):
                    camera.resume()
                # Check camera availability before changing controller mode.
                if hasattr(camera, 'snap'):
                    camera.snap()
                self._prepare(run, service)
                result = self.calibrate(run, service, camera)
            else:
                from pick_and_hold.Calibration.fast_disk import ensure_arrival
                ensure_arrival(service.pose_mm(), self.context['pose'])
                if run.stopped():
                    raise RuntimeError('Stopped before alignment')
                self._prepare(run, service)
                ensure_arrival(service.pose_mm(), self.context['pose'])
                result = self.align(run, service, deepcopy(self.context['target']))
            self._checked(result)
            if run.stopped():
                raise RuntimeError('Stopped; step was not recorded as complete')
            pose = numbers(service.pose_mm(), ('X', 'Y', 'Z', 'Rz'))
            if action == 'Calibrate' and result.get('calibration_pose'):
                from pick_and_hold.Calibration.fast_disk import wrap
                image_pose = result['calibration_pose']
                if (any(abs(pose[k]-image_pose[k]) > .1 for k in ('X','Y','Z')) or
                        abs(wrap(pose['Rz']-image_pose['Rz'])) > .05):
                    raise RuntimeError('Arm moved before the confirmed calibration could be saved. Hold still and recalibrate.')
            joints = numbers(service.joints(), ('J1', 'J2', 'J3', 'J4'))
            stamp = utc_now()
            if action == 'Calibrate' and not result.get('target', {}).get('converged'):
                raise RuntimeError('Calibration did not confirm convergence')
            with self.teaching.lock:
                data = self.teaching._load()
                draft = self.teaching._draft(data, dict(draft_id=ident, revision=revision))
                draft['waypoints'].append(dict(station=action, label=action, captured_at=stamp,
                    kind='executed_algorithm', pose_mm=pose, joints=joints, source='robot_controller',
                    command='fast_disk.run_fast_disk' if action == 'Calibrate' else 'Align.motion.seq_align',
                    result=deepcopy(result), images=[], gripper=None))
                draft['revision'] += 1
                self.teaching._store(data)
            if action == 'Calibrate':
                self.context = dict(draft_id=ident, captured_at=stamp, target=deepcopy(result['target']),
                                    pose=pose, time=time.monotonic())
            elif self.context:
                self.context['pose'] = pose  # Repeat Align only from its verified end position.
            self.message = action + ' completed and recorded. ' + ('Wide confirmed. Align is a separate automatic action.' if action == 'Calibrate' else 'Use Descend in Run to open the claw and lower to the plate.')
            if trace:
                trace.record('completed', result=result)
            return dict(ok=True)
        except Exception as error:
            if action == 'Calibrate':
                run.target = None
            logging.exception('Researcher %s failed', action)
            prior_log = getattr(run, 'log', [])
            if not prior_log or prior_log[-1].get('msg') != str(error):
                run.say(str(error), 'err')
            run.state = 'stopped' if run.stopped() else 'error'
            self.context = None
            self.message = ('Stopped. This step was not recorded as complete.' if run.stopped() else
                            action + ' did not finish. Check camera visibility and controller readiness; details are in Developer view. No completed step was recorded.')
            if trace:
                trace.record('stopped' if run.stopped() else 'failed', error=str(error))
            return dict(ok=False, error=str(error))
        finally:
            self.active_step = None
