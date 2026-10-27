"""Explicit button replay of the exact latest tested empty-gripper route."""
import hashlib
import json
import threading
import time
from pathlib import Path

from recorded_return import RecordedReturn
from researcher_teaching import TeachingError
from trajectory_queue import prepare_points

PATH_ID = '6d532ee8f22607688bee8943e05449415c7a0ad15c59a895f91cd3d251d3c420'
SPEED = 137


class LatestHamilton(RecordedReturn):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root = self.folder.parent.parent/'reports/trajectory_smoothing'
        self.attempts = self.root/'latest_button_runs'
        self.lock = threading.RLock()
        self.executor = 'lua_queue'
        self.message = 'Latest tested route: Home-area ↔ Hamilton.'

    def reviewed(self):
        original, source_id, _ = self.load(recovery=True)
        raw = (self.root/'entry_forward_3mm/candidate.json').read_bytes()
        candidate = json.loads(raw)
        parent = (self.root/'pruned_middle/candidate.json').read_bytes()
        if (hashlib.sha256(raw).hexdigest() != PATH_ID or
                candidate.get('source_sha256') != source_id or
                candidate.get('parent_candidate_sha256') != hashlib.sha256(parent).hexdigest()):
            raise TeachingError('The saved route changed. Ask the developer to review it.')
        return original, source_id, candidate['routes']['to_hamilton']

    def public(self, robot):
        run = self.get_runner()
        active = run.active and run.name == 'recorded_return'
        result = dict(active=active, can_start=False, direction=None, path_id=PATH_ID,
                      speed=SPEED, progress=self.progress, message=self.message, blocker='')
        try:
            original, _, _ = self.reviewed()
            self.check_previous_attempt()
            if run.active:
                raise TeachingError('Wait for the current movement to finish.')
            if not robot.get('connected') or not robot.get('ok') or robot.get('errors'):
                raise TeachingError('Connect the robot and resolve its controller alert.')
            pose, q = robot.get('pose_mm', {}), robot.get('joints', {})
            try:
                self.match_start(pose, q, original['trajectory'][0])
                result['direction'] = 'toward_home'
            except TeachingError:
                try:
                    self.match_start(pose, q, original['trajectory'][-1])
                    result['direction'] = 'to_hamilton'
                except TeachingError:
                    raise TeachingError('Move to the recorded Home-area or Hamilton endpoint first. No connecting move is added.') from None
            queue = self.queue_status()
            if not queue.get('available') or queue.get('max_speed_mm_s', 0) < SPEED:
                raise TeachingError('Publish the tested 137 controller package in Developer setup.')
            result['can_start'] = True
        except TeachingError as error:
            result['blocker'] = str(error)
        except (OSError, ValueError, KeyError, TypeError):
            result['blocker'] = 'The saved route needs developer review.'
        return result

    def check_previous_attempt(self):
        from home_attempts import known_startup_refusal
        previous = sorted(self.attempts.glob('*.json'))
        for path in reversed(previous):
            try:
                record = json.loads(path.read_text())
                if known_startup_refusal(record):
                    continue
                if record.get('status') == 'completed':
                    return
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            raise TeachingError('The previous route has no verified completion or proof that travel never started. '
                                'Ask the developer to review its log and the current arm position. '
                                'Resetting the controller does not resolve this saved attempt.')

    def home_prefix(self, pose, joints):
        """Pure reviewed Hamilton departure, or None for ordinary Home planning."""
        original, source_id, route = self.reviewed()
        first = original['trajectory'][0]
        try:
            self.match_start(pose, joints, first)
        except TeachingError:
            return None
        self.check_previous_attempt()
        vertices = list(reversed([route['start']] + route['points']))
        legs, endpoint_joints = prepare_points(first['pose_mm'], first['joints'], vertices[1:], self.params(),
                                              reviewed=True, reverse_entry=True)
        return dict(first=first, points=legs, endpoint=legs[-1], endpoint_joints=endpoint_joints,
                    path_id=PATH_ID, source_id=source_id, speed=SPEED)

    def execute_home_prefix(self, run, service, prefix):
        """Home's runner owns the full operation; no second sequence is started."""
        self.match_start(service.pose_mm(), service.joints() or {}, prefix['first'])
        from trajectory_queue import LuaTrajectory
        return LuaTrajectory(service).execute(run, prefix['first']['pose_mm'], service.joints(),
            prefix['points'], self.params(), SPEED,
            lambda stage, done, total: run.say(f'Home via taught Hamilton route: {stage} {done:.0f}/{total}'),
            reviewed=True, reverse_entry=True, research_speed137=True)

    def start(self, body):
        with self.lock:
            if body.get('ready') is not True:
                raise TeachingError('Confirm empty gripper, clear route, released arm and supervised E-stop.')
            service, run = self.get_service(), self.get_runner()
            status = self.public(service.status())
            if not status['can_start']:
                raise TeachingError(status['blocker'])
            if body.get('path_id') != PATH_ID or body.get('direction') != status['direction']:
                raise TeachingError('The starting endpoint changed. Refresh before running.')
            original, source_id, route = self.reviewed()
            reverse = status['direction'] == 'toward_home'
            first = original['trajectory'][0 if reverse else -1]
            vertices = [route['start']] + route['points']
            if reverse:
                vertices.reverse()
            cfg = self.params()
            legs, _ = prepare_points(first['pose_mm'], first['joints'], vertices[1:], cfg,
                                     reviewed=True, forward_entry=not reverse, reverse_entry=reverse)
            self.attempts.mkdir(parents=True, exist_ok=True)
            permission = self.attempts/f'{time.time_ns()}.json'
            grant = dict(path_sha256=PATH_ID, source_sha256=source_id, direction=status['direction'],
                         speed=SPEED, status='requested', attempt_available=True, allow_explicit_repeats=False,
                         clearance_approved=True, workspace_box_exception=True, executor='lua_queue',
                         route_kind='latest_reviewed_entry', authorization='Explicit UI button and readiness confirmation')
            permission.write_text(json.dumps(grant, indent=2), encoding='utf-8')
            self.invalidate()
            response = run.start('recorded_return', self.execute, service, {'trajectory':[first]}, PATH_ID,
                                 grant, legs, cfg, permission, True, False, False, False,
                                 not reverse, reverse, False, False, False, False, False, False, True)
            if not response.get('ok'):
                raise TeachingError('Another action is using the arm. Inspect the pending attempt before retrying.')
            return dict(ok=True, message='Latest taught route requested at 137. Keep hands clear.')
