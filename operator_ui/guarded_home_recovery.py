"""One-use, operator-reviewed Home recovery through the existing monitored executor.

Preview never changes controller state. An old failure is resolved only after
verified recovery completion; failure, restart or lost completion stays blocked.
"""
from copy import deepcopy
import json
import math
import threading
import time
from uuid import uuid4

from autonomy import check_path, wrap
from ik_home import compare_snapshot
from reviewed_home import ReviewedHomeConnection
from researcher_teaching import TeachingError


class GuardedHomeRecovery:
    def __init__(self, connection):
        self.connection = connection
        self.pending = {}

    def _ready(self):
        home = self.connection.home
        run = home.get_runner()
        state = home.get_service().status()
        if run.active or getattr(run, 'reserved', False):
            raise TeachingError('Stop other workflows before recovery.')
        if (not state.get('connected') or not state.get('ok') or state.get('errors')
                or state.get('enabled') is not False
                or state.get('program_state', {}).get('state') != 'stopped'):
            raise TeachingError('Recovery requires a fault-free, disabled, stopped controller.')
        if home.get_draggo().public(state).get('state') != 'off':
            raise TeachingError('End hand-guiding before recovery.')
        e1 = state.get('external_axes', {}).get('E1')
        if type(e1) not in (int, float) or not math.isfinite(e1) or abs(e1) > .1:
            raise TeachingError('Recovery requires an inspected empty, closed gripper.')
        return state

    @staticmethod
    def validate_dense(plan):
        current, joints = dict(plan['start']), dict(plan['joints'])
        count = 0
        for stage in plan['stages']:
            targets = stage['points'] if stage['kind'] == 'queue' else [{**current, 'Rz': stage['rz']}]
            for target in targets:
                origin = dict(current)
                steps = max(1, math.ceil(math.dist([origin[k] for k in ('X','Y','Z')],
                                                  [target[k] for k in ('X','Y','Z')])),
                            math.ceil(abs(wrap(target['Rz'] - origin['Rz'])) / .5))
                for i in range(1, steps + 1):
                    point = {k: origin[k] + (target[k] - origin[k])*i/steps for k in ('X','Y','Z')}
                    point['Rz'] = origin['Rz'] + wrap(target['Rz'] - origin['Rz'])*i/steps
                    joints = check_path(current, point, joints, plan['cfg'], plan['envelope'])
                    joints['J1'] = plan['joints']['J1'] + point['Z'] - plan['start']['Z']
                    if not 0 <= joints['J1'] <= 400 or abs(joints['J3']) > 180:
                        raise TeachingError('Recovery exceeds joint travel limits.')
                    current = point
                    count += 1
        return count

    def preview(self):
        self._ready()
        unresolved = self.connection.unresolved_attempts()
        route = self.connection.home.hamilton_route
        route_unresolved = route.blocking_attempts() if route else {}
        if not unresolved:
            raise TeachingError('No unresolved Home attempt; use normal Return Home.')
        plan = self.connection._propose_current()
        samples = self.validate_dense(plan)
        state = self._ready()
        compare_snapshot(plan, state, plan['cfg'], plan['envelope'], plan['home'], plan['target_id'])
        if unresolved != self.connection.unresolved_attempts():
            raise TeachingError('Failure history changed during preview.')
        if route and route_unresolved != route.blocking_attempts():
            raise TeachingError('Route history changed during preview.')
        plan.update(id=uuid4().hex, recovery_of=unresolved, expires_at=time.time()+300,
                    route_recovery_of=route_unresolved,
                    dense_samples=samples, physical_clearance_verified=False)
        # New previews invalidate old ones. Restart also invalidates all pending tokens.
        self.pending = {plan['id']: deepcopy(plan)}
        folder = self.connection.folder/'recovery_previews'
        folder.mkdir(parents=True, exist_ok=True)
        with (folder/(plan['id']+'.json')).open('x', encoding='utf-8') as stream:
            json.dump(plan, stream, indent=2, allow_nan=False)
        return dict(ok=True, plan=deepcopy(plan), motion_sent=False)

    def confirm(self, body):
        required = ('ready', 'empty_gripper', 'cell_clear', 'operator_checked_recovery', 'reviewed_failure')
        if any(body.get(key) is not True for key in required):
            raise TeachingError('Confirm reviewed failure, corrected condition, empty claws and the displayed clear route.')
        if not isinstance(body.get('review_notes'), str) or not body['review_notes'].strip():
            raise TeachingError('Include the failure review and operator correction in review_notes.')
        plan = self.pending.get(body.get('plan_id'))
        if plan is None or time.time() > plan['expires_at']:
            raise TeachingError('Recovery preview expired or was used; request a fresh preview.')
        self._ready()
        if self.connection.unresolved_attempts() != plan['recovery_of']:
            raise TeachingError('Failure history changed; review again.')
        route = self.connection.home.hamilton_route
        if (route.blocking_attempts() if route else {}) != plan['route_recovery_of']:
            raise TeachingError('Route history changed; review again.')
        fresh = self.connection._propose_current()
        compare_snapshot(plan, self._ready(), fresh['cfg'], fresh['envelope'], fresh['home'], fresh['target_id'])
        if (plan['points_sha256'] != fresh['points_sha256']
                or not ReviewedHomeConnection.same_stages(plan['stages'], fresh['stages'])):
            raise TeachingError('Recovery route changed; preview again.')
        self.validate_dense(fresh)
        self.pending.pop(plan['id'])  # Never retry this approval after a dispatch exception.
        plan = deepcopy(plan)
        plan.update(review_notes=body['review_notes'].strip(), physical_clearance_verified=True)
        run = self.connection.home.get_runner()
        token = object()
        if not run.reserve(token, threading.Event()):
            raise TeachingError('Another workflow owns the controller.')
        try:
            run.claim(token)
            result, attempt = self.connection._dispatch(plan)
            worker = run._thread
        except Exception:
            run.release(token)
            raise

        def finish():
            try:
                worker.join()
                sequence = deepcopy(run.snapshot())
                self.connection.finish(attempt, sequence)
                if sequence.get('state') == 'done' and (sequence.get('result') or {}).get('ok') is True:
                    state = self.connection.home.get_service().status()
                    home = plan['home']
                    verified = (state.get('connected') and state.get('ok') and not state.get('errors')
                        and all(type(state.get('pose_mm', {}).get(k)) in (int, float)
                                and math.isfinite(state['pose_mm'][k])
                                and abs(state['pose_mm'][k]-v) <= .1 for k, v in home.items())
                        and all(type(state.get('joints', {}).get(k)) in (int, float)
                                and math.isfinite(state['joints'][k])
                                and abs(state['joints'][k]-v) <= .1
                                for k, v in plan['checked'][-1]['joints'].items()))
                    record = json.loads(attempt.read_text(encoding='utf-8'))
                    record.update(recovery_home_verified=bool(verified), recovery_end_state=state)
                    if not verified:
                        record['status'] = 'recovery_completion_unverified'
                    attempt.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')
            finally:
                run.release(token)

        threading.Thread(target=finish, daemon=True).start()
        return dict(**result, recovery_attempt=str(attempt))
