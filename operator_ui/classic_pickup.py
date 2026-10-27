"""The researcher console's pickup, optionally followed by slow lift and Home.

This presses the four classic buttons in order — Calibrate, Align, Descend,
Grip — through their real entry points:

    PlateTeaching.start('Calibrate', …)   -> job 'researcher_calibrate'
    PlateTeaching.start('Align', …)       -> job 'researcher_align'
    ResearcherDescent.start(…)            -> job 'researcher_descend'
    ReferenceGrip.start(…)                -> job 'position_grip' (stable UI job ID)

Each runs as its own Runner job, exactly as a click would, so every
precondition those wrappers enforce still applies: the align-freshness
window, the envelope check, the descent receipt and its id handshake, the
controller preparation each one does for itself. Nothing is called through
a side door, and no step is re-implemented here.

The configured production workflow then lifts 5 mm at speed 5 and invokes
the same IK Home entry point as Lacry, without an inspection pause or a
separate 25 mm lift. The researcher confirms the complete loaded route once.
"""
from copy import deepcopy
import threading
import time

from researcher_teaching import TeachingError

STEP_TIMEOUT_S = 1200
POLL_S = 0.25

STEPS = (
    ('Calibrate', 'researcher_calibrate', 'Calibrate the two-disk plate'),
    ('Align',     'researcher_align',     'Align with the plate'),
    ('Descend',   'researcher_descend',   'Descent'),
    ('Grip',      'position_grip',        'Grip the plate'),
)
TRANSPORT_STEPS = (
    ('Lift', 'pickup_slow_lift', 'Lift the plate 5 mm'),
    ('Home', 'researcher_home', 'Return Home'),
)


class ClassicPickup:
    def __init__(self, teaching, plate_teaching, descent, grip, get_service, get_runner, transport=None):
        self.teaching, self.plate_teaching = teaching, plate_teaching
        self.descent, self.grip = descent, grip
        self.get_service, self.get_runner = get_service, get_runner
        self.transport = transport
        self.steps = STEPS + TRANSPORT_STEPS if transport is not None else STEPS
        self.lock = threading.RLock()
        self.thread = None
        self.cancel = threading.Event()
        self.state = dict(active=False, step=None, done=[], ok=None, error='',
                          message=('Calibrate, Align, Descent, Grip, slow lift and Return Home.'
                                   if transport is not None else
                                   'Runs Calibrate, Align, Descent and Grip in order.'))

    # ------------------------------------------------------------------ view
    def public(self):
        with self.lock:
            state = deepcopy(self.state)
        run = self.get_runner()
        blocker = ''
        if state['active']:
            blocker = 'The pickup sequence is already running.'
        elif run.active or getattr(run, 'reserved', False):
            blocker = 'Another action is running. Wait for it to finish.'
        elif hasattr(self.grip, 'configuration_ready'):
            try:self.grip.configuration_ready()
            except TeachingError as error:blocker=str(error)
        if not blocker and self.transport is not None:
            try:self.transport.configuration_ready()
            except TeachingError as error:blocker=str(error)
        state['can_start'], state['blocker'] = not blocker, blocker
        return state

    def _note(self, **fields):
        with self.lock:
            self.state.update(**fields)

    def labels(self):
        return [label for _, _, label in self.steps]

    # --------------------------------------------------------------- running
    def start(self, on_finish=None, home_prefix=None, continuation=None, tail_steps=None,
              completion_message=None, include_pickup=True, prefix_steps=None):
        if type(include_pickup) is not bool or (not include_pickup and (not tail_steps or home_prefix or continuation)):
            raise TeachingError('A delivery-only workflow requires its complete checked task sequence.')
        steps=self.steps if include_pickup else ()
        first_label=prefix_steps[0]['label'] if prefix_steps else ('Return Home' if home_prefix else (steps[0][2] if steps else tail_steps[0]['label']))
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise TeachingError('The pickup sequence is already running.')
            if self.get_runner().active:
                raise TeachingError('Another action is running. Wait for it to finish.')
            if include_pickup and hasattr(self.grip, 'configuration_ready'):
                self.grip.configuration_ready()
            if include_pickup and self.transport is not None:
                self.transport.configuration_ready()
            if include_pickup:self._draft_body()
            self.cancel = threading.Event()
            token = object()
            if not self.get_runner().reserve(token, self.cancel):
                raise TeachingError('Another action is running. Wait for it to finish.')
            self.state = dict(active=True, step=first_label, done=[], ok=None, error='',
                              results=[], started_at=time.time(),
                              message='Starting the confirmed workflow. Keep hands clear.')
            self.thread = threading.Thread(target=self._run,
                args=(on_finish,token,home_prefix,continuation,tail_steps,completion_message,steps,prefix_steps), daemon=True)
            try:
                self.thread.start()
            except Exception:
                self.get_runner().release(token)
                self.state['active'] = False
                raise
        return dict(ok=True, message=('Running the pickup sequence. Keep hands clear.' if include_pickup
                                    else 'Running the confirmed imaging workflow. Keep hands clear.'))

    def stop(self):
        run = self.get_runner()
        self._note(message='Stop requested. The movement in progress finishes first.')
        self.cancel.set()
        run.request_stop()
        return dict(ok=True, message='Stop requested. The current movement finishes first; '
                                     'use the physical emergency stop if you need it now.')

    def _draft_body(self):
        """PlateTeaching rejects a stale draft id/revision, same as the UI."""
        draft = (self.teaching.public() or {}).get('draft')
        if not draft:
            raise TeachingError('No teaching draft is open. Start one in the classic view, '
                                'or capture Home first.')
        return dict(ready=True, draft_id=draft['id'], revision=draft['revision'])

    def _dispatch(self, action):
        if action == 'Lift':
            return self.transport.start_lift(deepcopy(self.get_runner().result or {}))
        if action == 'Home':
            return self.transport.start_home(deepcopy(self.get_runner().result or {}))
        if action in ('Calibrate', 'Align'):
            return self.plate_teaching.start(action, self._draft_body())
        if action == 'Descend':
            return self.descent.start(dict(ready=True))
        ready = self.grip.public(self.get_service().status())
        if not ready.get('can_start'):
            raise TeachingError('Grip is not ready: ' + str(ready.get('blocker') or 'unknown'))
        return self.grip.start(dict(ready=True, descent_id=ready.get('descent_id')))

    def _await(self, job, label, timeout_s=STEP_TIMEOUT_S):
        run = self.get_runner()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if run.name == job and not run.active:
                break
            time.sleep(POLL_S)
        else:
            self.stop()
            raise TeachingError(label + ' did not finish in time. Check the classic view.')
        if run.name != job:
            raise TeachingError('Another action replaced ' + label + '. Nothing further was run.')
        result = run.result or {}
        if run.stopped() or run.state == 'stopped':
            raise TeachingError(label + ' was stopped. Nothing further was run.')
        if run.state != 'done' or result.get('ok') is not True:
            raise TeachingError(label + ' did not complete: '
                                + str(result.get('error') or 'see the classic view') + '.')
        return result

    def _run(self, on_finish, token, home_prefix=None, continuation=None, tail_steps=None,
             completion_message=None, steps=None, prefix_steps=None):
        steps=self.steps if steps is None else steps
        done = []
        label = 'Return Home' if home_prefix else (steps[0][2] if steps else tail_steps[0]['label'])
        run = self.get_runner()
        try:
            run.claim(token)
            for task in prefix_steps or []:
                label = task['label']
                if self.cancel.is_set():
                    raise TeachingError('Stopped before ' + label + '.')
                self._note(step=label, done=list(done), message=label+'.')
                dispatched = task['start']()
                if not dispatched or dispatched.get('ok') is not True:
                    raise TeachingError((dispatched or {}).get('error') or label+' was not started.')
                try:
                    self._await(dispatched['started'], label, task.get('timeout_s',STEP_TIMEOUT_S))
                finally:
                    with self.lock:
                        self.state['results'].append(dict(step=label, sequence=run.name,
                            run_id=run.run_id, state=run.state, result=deepcopy(run.result),
                            log=deepcopy(run.log)))
                done.append(label)
            if home_prefix:
                label = 'Return Home'
            run.audit('classic_pickup_started', workflow=self.state['started_at'])
            if home_prefix:
                if self.cancel.is_set():
                    raise TeachingError('Stopped before Return Home.')
                self._note(step=label, message='Returning Home before calibration. Keep hands clear.')
                previous_id = run.run_id
                dispatched = None
                try:
                    dispatched = home_prefix['start']()
                    if not dispatched or dispatched.get('ok') is not True:
                        raise TeachingError((dispatched or {}).get('error') or 'Return Home was not started.')
                    if dispatched.get('started'):
                        self._await(dispatched['started'], label)
                finally:
                    home_prefix['finish']()
                    with self.lock:
                        self.state['results'].append(
                            dict(step=label, sequence=run.name, run_id=run.run_id,
                                 state=run.state, result=deepcopy(run.result))
                            if run.run_id != previous_id else
                            dict(step=label, motion_started=False, response=deepcopy(dispatched)))
                if self.cancel.is_set():
                    raise TeachingError('Stopped after Return Home. Calibration was not started.')
                home_prefix['verify']()
                done.append(label)
                run.audit('pickup_home_prefix_verified')
            for action, job, label in steps:
                if self.cancel.is_set():
                    raise TeachingError('Stopped before ' + label + '.')
                self._note(step=label, done=list(done),
                           message=label + ' running. Keep hands clear.')
                dispatched = self._dispatch(action)
                if not dispatched or dispatched.get('ok') is not True:
                    raise TeachingError((dispatched or {}).get('error') or label + ' was not started.')
                try:
                    result = self._await(job, label)
                finally:
                    if action == 'Home' and self.transport is not None:
                        self.transport.finish_home(run.snapshot())
                    with self.lock:
                        self.state['results'].append(dict(step=label, sequence=job,
                            run_id=run.run_id, state=run.state, result=deepcopy(run.result),
                            target=deepcopy(run.target), log=deepcopy(run.log)))
                done.append(label)
            if continuation:
                label = continuation['label']
                if self.cancel.is_set():
                    raise TeachingError('Stopped before ' + label + '.')
                self._note(step=label, done=list(done), message=label + ' running. Keep hands clear.')
                dispatched = continuation['start']()
                if not dispatched or dispatched.get('ok') is not True:
                    raise TeachingError((dispatched or {}).get('error') or label + ' was not started.')
                try:
                    self._await(dispatched['started'], label)
                finally:
                    with self.lock:
                        self.state['results'].append(dict(step=label, sequence=run.name,
                            run_id=run.run_id, state=run.state, result=deepcopy(run.result),
                            target=deepcopy(run.target), log=deepcopy(run.log)))
                done.append(label)
            for task in tail_steps or []:
                label = task['label']
                if self.cancel.is_set():
                    raise TeachingError('Stopped before ' + label + '.')
                self._note(step=label, done=list(done), message=label+'.')
                dispatched = task['start']()
                if not dispatched or dispatched.get('ok') is not True:
                    raise TeachingError((dispatched or {}).get('error') or label+' was not started.')
                try:
                    self._await(dispatched['started'], label, task.get('timeout_s',STEP_TIMEOUT_S))
                finally:
                    with self.lock:
                        self.state['results'].append(dict(step=label, sequence=run.name,
                            run_id=run.run_id, state=run.state, result=deepcopy(run.result),
                            log=deepcopy(run.log)))
                done.append(label)
            message = ('Pickup sequence complete. The arm is at Home; confirm the plate stayed secure.'
                       if self.transport is not None else
                       'Calibration, alignment, descent and grip complete. '
                       'Claw reached the saved setting; inspect the hold before lifting.')
            if continuation:
                message = continuation['message']
            if completion_message:
                message = completion_message
            self._note(active=False, step=None, done=done, ok=True,message=message)
        except Exception as error:               # noqa: BLE001 — reported to the researcher
            detail = str(error)
            if 'disk not detected' in detail:
                detail = ('Both disks are not visible. Return to the camera viewing position '
                          '(normally saved Home), check Camera View, then request a new run.')
            self._note(active=False, step=label, done=done, ok=False, error=str(error),
                       message='Pickup stopped during ' + label + ': ' + detail)
        finally:
            try:
                run.audit('classic_pickup_finished', workflow_result=deepcopy(self.state))
                if on_finish:
                    with self.lock:
                        final = deepcopy(self.state)
                    try:
                        on_finish(final)
                    except Exception:
                        pass
            finally:
                run.release(token)
