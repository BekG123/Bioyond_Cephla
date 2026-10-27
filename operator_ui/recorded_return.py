"""Explicit recorded traversals with a path-bound workspace-box exception.

Never changes the saved workspace or Home. Joint/reach checks remain mandatory.
"""
import hashlib
import json
import math
import time
from pathlib import Path

from autonomy import TransferError, check_path, ensure_arrival, wrap
from researcher_teaching import TeachingError
from trajectory_queue import LuaTrajectory, prepare_points


class RecordedReturn:
    def __init__(self, folder, get_service, get_runner, params, prepare, invalidate):
        self.folder = Path(folder)
        self.get_service, self.get_runner = get_service, get_runner
        self.params, self.prepare, self.invalidate = params, prepare, invalidate
        self.message = 'Replay the taught Hamilton return to its demonstrated endpoint.'
        self.progress = 0
        self.executor = 'stepwise'
        self._queue_status = dict(available=False,message='Checking controller queue support.')
        self._queue_checked = 0

    def queue_status(self):
        if time.monotonic()-self._queue_checked > 3:
            self._queue_status = LuaTrajectory(self.get_service()).capability()
            self._queue_checked = time.monotonic()
        return self._queue_status

    def load(self, *, recovery=False):
        grant = json.loads((self.folder/'replay_permission.json').read_text(encoding='utf-8-sig'))
        raw = (self.folder/'return_path.json').read_bytes()
        ident = hashlib.sha256(raw).hexdigest()
        if (grant.get('path_sha256') != ident or grant.get('workspace_box_exception') is not True
                or (not recovery and grant.get('attempt_available') is not True)):
            raise TeachingError('This recorded path has no unused replay permission.')
        speed = grant.get('speed',10)
        if type(speed) not in (int,float) or not math.isfinite(speed) or not 0 < speed <= 40:
            raise TeachingError('Recorded-path speed must be greater than zero and at most 40 mm/s.')
        data = json.loads(raw)
        samples = (self.folder/'samples.jsonl').read_bytes()
        if data['source']['sha256'] != hashlib.sha256(samples).hexdigest():
            raise TeachingError('Recording changed; review the return path again.')
        if not data['validation'].get('kinematics_passed'):
            raise TeachingError('The recorded path has not passed kinematic review.')
        return data, ident, grant

    def recovery_plan(self, pose, joints):
        """Retrace a stopped Hamilton approach; never invent an approach shortcut."""
        data, ident, grant = self.load(recovery=True)
        if grant.get('status') != 'stopped_or_failed' or grant.get('direction') != 'to_hamilton':
            raise TeachingError('Recovery requires a reviewed stopped Hamilton approach.')
        directed = self.directed(data, 'to_hamilton')
        first = directed['trajectory'][0]
        legs, cfg = self.plan(directed)
        points, _ = prepare_points(first['pose_mm'], first['joints'], legs, cfg)
        vertices = [first['pose_mm']] + points
        candidates = []
        q = first['joints']
        previous = vertices[0]
        for index, point in enumerate(vertices):
            q = check_path(previous, point, q, cfg, None)
            distance = math.dist([pose[k] for k in ('X','Y','Z')], [point[k] for k in ('X','Y','Z')])
            yaw = abs(wrap(pose['Rz']-point['Rz']))
            if distance <= .15 and yaw <= .15 and all(abs(joints[k]-q[k]) <= .5 for k in ('J2','J3','J4')):
                candidates.append((distance*distance+yaw*yaw,index))
            previous = point
        if not candidates:
            raise TeachingError('Current pose and IK branch do not match a stopped taught waypoint; no recovery approach added.')
        _, index = min(candidates)
        if index == 0 or any(abs(i-index)>1 for _,i in candidates):
            raise TeachingError('Recovery start is already at the endpoint or is ambiguous.')
        poses = [dict(pose)] + list(reversed(vertices[:index+1]))
        q, rows = dict(joints), []
        previous = pose
        for i, point in enumerate(poses):
            q = check_path(previous, point, q, cfg, None)
            rows.append(dict(valid=True,elapsed_s=i*.2,pose_mm=point,joints=dict(q)))
            previous = point
        recovery = {**data,'trajectory':rows}
        legs, cfg = self.plan(recovery)
        review = dict(path_id=ident,matched_waypoint=index,start=pose,joints=joints,
                      endpoint=vertices[0],points=legs,previous_permission=grant,
                      method='Reverse taught prefix; every segment checked with IK and joint/reach limits.')
        return recovery, ident, grant, legs, cfg, review

    def start_recovery(self, body):
        if body.get('ready') is not True:
            raise TeachingError('Confirm empty gripper, released arm, clear taught path and supervised E-stop.')
        service, run = self.get_service(), self.get_runner()
        robot = service.status()
        if run.active or not robot.get('connected') or not robot.get('ok') or robot.get('errors'):
            raise TeachingError('Recovery requires an idle connected robot without controller alerts.')
        try:
            data, ident, grant, legs, cfg, review = self.recovery_plan(service.pose_mm(), service.joints() or {})
        except (TransferError, KeyError, TypeError, ValueError) as error:
            raise TeachingError(f'Recovery rejected: {error}') from None
        if body.get('path_id') != ident or body.get('matched_waypoint') != review['matched_waypoint']:
            raise TeachingError('Recovery review changed; review the current pose and matched waypoint.')
        support = LuaTrajectory(service).capability()
        if not support['available']:
            raise TeachingError(support['message'])
        review['requested_at'] = time.time()
        review['authorization'] = body.get('authorization','Explicit return-to-start request')
        review_path = self.folder/f'recovery_review_{time.time_ns()}.json'
        review_path.write_text(json.dumps(review,indent=2),encoding='utf-8')
        grant = {**grant,'direction':'recover_start','executor':'lua_queue','recovery_review':review_path.name}
        self.invalidate()
        self.executor = 'lua_queue'
        result = run.start('recorded_return',self.execute,service,data,ident,grant,legs,cfg)
        if not result.get('ok'):
            raise TeachingError('Another task is using the arm.')
        return dict(ok=True,message='Retracing the taught approach to its original start.',review=review_path.name)

    @staticmethod
    def match_start(pose, joints, sample):
        try:
            ensure_arrival(pose, sample['pose_mm'])
            if any(abs(joints[k]-sample['joints'][k]) > .5 for k in ('J1','J2','J3','J4')):
                raise ValueError()
        except (TransferError, KeyError, TypeError, ValueError):
            p = sample['pose_mm']
            raise TeachingError(f"The selected path must start at X{p['X']:.2f}, Y{p['Y']:.2f}, Z{p['Z']:.2f}, Rz{p['Rz']:.2f}. Position and joint configuration must match; no approach movement is added.") from None

    def plan(self, data):
        rows = data['trajectory']
        if len(rows) < 2 or any(not r['valid'] for r in rows):
            raise TeachingError('Recorded return has invalid telemetry.')
        cfg = self.params()
        pose, q = rows[0]['pose_mm'], rows[0]['joints']
        check_path(pose, pose, q, cfg, None)
        legs = []
        for a,b in zip(rows, rows[1:]):
            if not 0 < b['elapsed_s']-a['elapsed_s'] <= 1:
                raise TeachingError('Recorded return has a telemetry gap.')
            target = b['pose_mm']
            # Keep the recorded polyline; only omit sub-resolution stationary jitter.
            distance = math.dist([pose[k] for k in ('X','Y','Z')],[target[k] for k in ('X','Y','Z')])
            yaw = wrap(target['Rz']-pose['Rz'])
            if distance < .02 and abs(yaw) < .02 and b is not rows[-1]:
                continue
            count = max(1, math.ceil(distance/5), math.ceil(abs(yaw)))
            origin = pose
            for i in range(1,count+1):
                point = {k:origin[k]+(target[k]-origin[k])*i/count for k in ('X','Y','Z')}
                point['Rz'] = origin['Rz']+yaw*i/count
                q = check_path(pose,point,q,cfg,None)
                legs.append(point)
                pose = point
        if not legs:
            raise TeachingError('No movement was recorded.')
        return legs, cfg

    @staticmethod
    def directed(data, direction):
        if direction == 'toward_home':
            return data
        if direction != 'to_hamilton':
            raise TeachingError('Choose toward_home or to_hamilton.')
        rows = data['trajectory']
        end = rows[-1]['elapsed_s']
        return {**data,'trajectory':[{**r,'elapsed_s':end-r['elapsed_s']} for r in reversed(rows)]}

    def public(self, robot):
        run = self.get_runner()
        active = run.active and run.name == 'recorded_return'
        blocker, ident, direction = '', None, 'toward_home'
        if active:
            return dict(active=True,can_start=False,message=self.message,progress=self.progress,blocker='',path_id=None,
                        executor=self.executor,queue=self._queue_status)
        try:
            data, ident, _ = self.load()
            if run.active:
                raise TeachingError('Wait for the current movement to finish.')
            if not robot.get('connected') or not robot.get('ok') or robot.get('errors'):
                raise TeachingError('Connect the robot and resolve any controller alert.')
            pose, joints = robot.get('pose_mm',{}), robot.get('joints',{})
            try:
                self.match_start(pose,joints,data['trajectory'][0])
            except TeachingError:
                direction = 'to_hamilton'
                self.match_start(pose,joints,data['trajectory'][-1])
        except TeachingError as error:
            blocker = str(error)
        except (OSError, ValueError, KeyError, TypeError):
            blocker = 'Recorded-return data is unavailable. Ask the developer to review it.'
        return dict(active=False,can_start=not blocker,message=self.message,progress=self.progress,
                    blocker=blocker,path_id=ident,direction=direction,executor=self.executor,
                    queue=self.queue_status() if robot.get('connected') else dict(available=False,message='Connect the robot to check queue support.'))

    def start(self, body):
        if body.get('ready') is not True:
            raise TeachingError('Confirm empty gripper, released arm, clear taught path and supervised E-stop.')
        service, run = self.get_service(), self.get_runner()
        ready = self.public(service.status())
        if not ready['can_start']:
            raise TeachingError(ready['blocker'])
        data, ident, grant = self.load()
        if body.get('path_id') != ident:
            raise TeachingError('The return path changed. Refresh and review it.')
        direction = body.get('direction')
        data = self.directed(data,direction)
        executor = body.get('executor','stepwise')
        if executor not in ('stepwise','lua_queue'):
            raise TeachingError('Choose stepwise or Lua queued replay.')
        if executor == 'lua_queue':
            support = LuaTrajectory(service).capability()
            if not support['available']:
                raise TeachingError(support['message'])
        self.match_start(service.pose_mm(),service.joints() or {},data['trajectory'][0])
        try:
            legs, cfg = self.plan(data)
        except TransferError as error:
            raise TeachingError(f'Recorded return rejected: {error}') from None
        self.invalidate()
        grant = {**grant,'direction':direction,'executor':executor}
        self.executor = executor
        result = run.start('recorded_return',self.execute,service,data,ident,grant,legs,cfg)
        if not result.get('ok'):
            raise TeachingError('Another task is using the arm.')
        return dict(ok=True,message='Recorded return requested. Keep hands clear.')

    def start_pruned(self, body):
        """Execute only the separately approved, hash-bound loop-removal artifact."""
        if body.get('ready') is not True:
            raise TeachingError('Confirm empty gripper, released arm, clear approved route and supervised E-stop.')
        service,run=self.get_service(),self.get_runner()
        robot=service.status()
        if run.active or not robot.get('connected') or not robot.get('ok') or robot.get('errors'):
            raise TeachingError('An idle connected robot without controller alerts is required.')
        original,source_id,_=self.load(recovery=True)
        variant=body.get('route','pruned')
        if variant not in ('pruned','vertical','straight','straight_212','return_212','straight_212_return','entry_forward_3mm','entry_speed47_to_hamilton','entry_speed47_toward_home','entry_speed55_to_hamilton','entry_speed55_toward_home','entry_speed70_to_hamilton','entry_speed70_toward_home','entry_speed80_to_hamilton','entry_speed80_toward_home','entry_speed100_to_hamilton','entry_speed100_toward_home','entry_speed130_to_hamilton','entry_speed130_toward_home','entry_speed137_to_hamilton','entry_speed137_toward_home'):
            raise TeachingError('Unknown reviewed trajectory variant.')
        vertical_runs=variant=='vertical'
        straight=variant in ('straight','straight_212','straight_212_return')
        research_speed47=variant in ('entry_speed47_to_hamilton','entry_speed47_toward_home')
        research_speed55=variant in ('entry_speed55_to_hamilton','entry_speed55_toward_home')
        research_speed70=variant in ('entry_speed70_to_hamilton','entry_speed70_toward_home')
        research_speed80=variant in ('entry_speed80_to_hamilton','entry_speed80_toward_home')
        research_speed100=variant in ('entry_speed100_to_hamilton','entry_speed100_toward_home')
        research_speed130=variant in ('entry_speed130_to_hamilton','entry_speed130_toward_home')
        research_speed137=variant in ('entry_speed137_to_hamilton','entry_speed137_toward_home')
        forward_entry=variant in ('entry_forward_3mm','entry_speed47_to_hamilton','entry_speed55_to_hamilton','entry_speed70_to_hamilton','entry_speed80_to_hamilton','entry_speed100_to_hamilton','entry_speed130_to_hamilton','entry_speed137_to_hamilton')
        reverse_entry=variant in ('entry_speed47_toward_home','entry_speed55_toward_home','entry_speed70_toward_home','entry_speed80_toward_home','entry_speed100_toward_home','entry_speed130_toward_home','entry_speed137_toward_home')
        level_return=variant=='return_212'
        review_root=self.folder.parent.parent/'reports/trajectory_smoothing'
        review_folder=review_root/({'vertical':'vertical_smoothing','straight':'straight_transfer',
                                   'straight_212':'straight_transfer_212','return_212':'return_to_start_212',
                                   'straight_212_return':'straight_212_return','entry_forward_3mm':'entry_forward_3mm',
                                   'entry_speed47_to_hamilton':'entry_speed47_to_hamilton',
                                   'entry_speed47_toward_home':'entry_speed47_toward_home',
                                   'entry_speed55_to_hamilton':'entry_speed55_to_hamilton',
                                   'entry_speed55_toward_home':'entry_speed55_toward_home',
                                   'entry_speed70_to_hamilton':'entry_speed70_to_hamilton',
                                   'entry_speed70_toward_home':'entry_speed70_toward_home',
                                   'entry_speed80_to_hamilton':'entry_speed80_to_hamilton',
                                   'entry_speed80_toward_home':'entry_speed80_toward_home',
                                   'entry_speed100_to_hamilton':'entry_speed100_to_hamilton',
                                   'entry_speed100_toward_home':'entry_speed100_toward_home',
                                   'entry_speed130_to_hamilton':'entry_speed130_to_hamilton',
                                   'entry_speed130_toward_home':'entry_speed130_toward_home',
                                   'entry_speed137_to_hamilton':'entry_speed137_to_hamilton',
                                   'entry_speed137_toward_home':'entry_speed137_toward_home'}.get(variant,'pruned_middle'))
        permission_path=review_folder/'replay_permission.json'
        if not permission_path.exists():
            raise TeachingError('This reviewed route has no one-run approval yet.')
        raw=(review_folder/'candidate.json').read_bytes()
        ident=hashlib.sha256(raw).hexdigest()
        candidate=json.loads(raw)
        grant=json.loads(permission_path.read_text(encoding='utf-8-sig'))
        direction=body.get('direction','toward_home')
        allowed_directions=('to_hamilton','toward_home') if vertical_runs or straight else ('toward_home',)
        if forward_entry:allowed_directions=('to_hamilton',)
        if variant=='straight_212_return':allowed_directions=('toward_home',)
        if (body.get('path_id')!=ident or grant.get('path_sha256')!=ident
                or grant.get('source_sha256')!=source_id or candidate.get('source_sha256')!=source_id
                or grant.get('attempt_available') is not True or grant.get('clearance_approved') is not True
                or grant.get('workspace_box_exception') is not True or direction not in allowed_directions or grant.get('direction')!=direction
                or grant.get('speed')!=(137 if research_speed137 else 130 if research_speed130 else 100 if research_speed100 else 80 if research_speed80 else 70 if research_speed70 else 55 if research_speed55 else 47 if research_speed47 else 40)):
            raise TeachingError('The shortened route lacks matching one-run approval.')
        if vertical_runs or straight or level_return or forward_entry or reverse_entry:
            parent=(review_root/'pruned_middle/candidate.json').read_bytes()
            if candidate.get('parent_candidate_sha256')!=hashlib.sha256(parent).hexdigest():
                raise TeachingError('The baseline shortened route changed; review smoothing again.')
        if level_return:
            forward=[candidate['start_sample']['pose_mm']]+candidate['points']
        elif straight or forward_entry or reverse_entry:
            route=candidate['routes']['to_hamilton']
            forward=[route['start']]+route['points']
        else:
            forward=[candidate['start']]+candidate['grouped']
        expected_count=2 if level_return else 3 if straight or forward_entry or reverse_entry else 75 if vertical_runs else 78
        if len(forward)!=expected_count+1:
            raise TeachingError(f'The approved route must contain exactly {expected_count} commands.')
        if level_return:
            ensure_arrival(forward[-1],original['trajectory'][-1]['pose_mm'])
            first=candidate['start_sample']
        else:
            ensure_arrival(forward[0],original['trajectory'][-1]['pose_mm'])
            ensure_arrival(forward[-1],original['trajectory'][0]['pose_mm'])
            first=original['trajectory'][0 if direction=='toward_home' else -1]
        self.match_start(service.pose_mm(),service.joints() or {},first)
        directed=list(reversed(forward)) if direction=='toward_home' and not level_return else forward
        cfg=self.params()
        legs,_=prepare_points(first['pose_mm'],first['joints'],directed[1:],cfg,reviewed=True,vertical_runs=vertical_runs,straight_transfer=straight,level_return=level_return,forward_entry=forward_entry,reverse_entry=reverse_entry)
        support=LuaTrajectory(service).capability()
        if not support['available']:raise TeachingError(support['message'])
        if grant['speed']>support.get('max_speed_mm_s',40):
            required=220108 if research_speed137 else 220107 if research_speed130 else 220106 if research_speed100 else 220105 if research_speed80 else 220104 if research_speed70 else 220103 if research_speed55 else 220102
            raise TeachingError(f"Speed {grant['speed']} requires publishing Lua queue version {required}; no motion started.")
        self.invalidate();self.executor='lua_queue'
        grant={**grant,'executor':'lua_queue','route_kind':'approved_reverse_entry' if reverse_entry else 'approved_forward_entry' if forward_entry else 'approved_level_return' if level_return else 'approved_straight' if straight else 'approved_vertical' if vertical_runs else 'approved_pruned','candidate_sha256':ident}
        result=run.start('recorded_return',self.execute,service,{'trajectory':[first]},ident,grant,legs,cfg,
                         permission_path,True,vertical_runs,straight,level_return,forward_entry,reverse_entry,research_speed47,research_speed55,research_speed70,research_speed80,research_speed100,research_speed130,research_speed137)
        if not result.get('ok'):raise TeachingError('Another task is using the arm.')
        return dict(ok=True,message=f'Approved {expected_count}-point route requested.',path_id=ident)

    def execute(self, run, service, data, ident, grant, legs, cfg, permission_path=None, reviewed=False, vertical_runs=False, straight_transfer=False, level_return=False,forward_entry=False,reverse_entry=False,research_speed47=False,research_speed55=False,research_speed70=False,research_speed80=False,research_speed100=False,research_speed130=False,research_speed137=False):
        self.progress = 0
        permission_path=Path(permission_path) if permission_path else self.folder/'replay_permission.json'
        # Persist consumption BEFORE preparing Auto. Never resume/retry after a restart.
        grant.update(attempt_available=False,status='attempt_started')
        permission_path.write_text(json.dumps(grant,indent=2),encoding='utf-8')
        def preflight():
            if run.stopped():
                raise TransferError('Stopped between recorded segments.')
            refusal = service._preflight()
            if refusal:
                raise TransferError(refusal)
            q = service.joints() or {}
            if (abs(q['J2']) > abs(cfg['j2_min_deg'])-cfg['j2_margin_deg'] or
                    abs(q['J4']) > min(cfg['j4_pref_abs_deg'],cfg['j4_hard_abs_deg']-5)):
                raise TransferError('Measured joints exceed automatic limits; no further recorded motion.')
        try:
            if run.stopped():
                raise TransferError('Stopped before controller preparation.')
            self.match_start(service.pose_mm(),service.joints() or {},data['trajectory'][0])
            self.prepare(run,service)
            preflight()
            self.match_start(service.pose_mm(),service.joints() or {},data['trajectory'][0])
            previous = data['trajectory'][0]['pose_mm']
            speed = grant.get('speed',10)
            run.say(f"Recorded path workspace-box exception; joint/reach checks remain active. Direction: {grant['direction']}; speed: {speed} mm/s")
            queued_result = {}
            if grant.get('executor') == 'lua_queue':
                def queue_progress(stage, done, total):
                    self.progress = 0 if stage == 'upload' else round(100*done/total)
                    self.message = (f'Loading taught path: {done} of {total} points (arm stationary).'
                                    if stage == 'upload' else 'Following the grouped taught path.')
                queued_result = LuaTrajectory(service).execute(run,previous,service.joints(),legs,cfg,speed,queue_progress,
                                                              grouped=not reviewed,reviewed=reviewed,vertical_runs=vertical_runs,straight_transfer=straight_transfer,level_return=level_return,forward_entry=forward_entry,reverse_entry=reverse_entry,research_speed47=research_speed47,research_speed55=research_speed55,research_speed70=research_speed70,research_speed80=research_speed80,research_speed100=research_speed100,research_speed130=research_speed130,research_speed137=research_speed137)
                if not queued_result.get('ok'):
                    raise TransferError(queued_result.get('error','Queued replay could not acquire the robot.'))
                previous = queued_result['endpoint']
            for i, point in enumerate(legs if grant.get('executor') != 'lua_queue' else [],1):
                preflight()
                actual, joints = service.pose_mm(), service.joints() or {}
                ensure_arrival(actual,previous)
                expected = check_path(actual,point,joints,cfg,None)
                self.message = f'Taught return: step {i} of {len(legs)}'
                run.say(self.message)
                result = service.move_cartesian(point['X'],point['Y'],point['Z'],point['Rz'],
                                                speed=speed,interpolation='linear',_recorded_box_exception=True)
                if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
                    raise TransferError(result.get('error') or 'Uncertain movement result; stopped without retry.')
                preflight()
                ensure_arrival(service.pose_mm(),point)
                after = service.joints() or {}
                if any(abs(after[k]-expected[k]) > .5 for k in ('J2','J3','J4')):
                    raise TransferError('Recorded return joint arrival mismatch; no retry.')
                self.progress = round(100*i/len(legs))
                previous = point
            self.message = ('At recorded Hamilton.' if grant['direction']=='to_hamilton' else
                            'At the demonstrated endpoint. Saved Home is unchanged.')
            grant['status'] = 'completed'
            grant['attempt_available'] = grant.get('allow_explicit_repeats') is True
            return dict(ok=True,endpoint=previous,path_id=ident,speed=speed,direction=grant['direction'],
                        executor=grant.get('executor','stepwise'),queue=queued_result,
                        route_kind=grant.get('route_kind','original_recording'))
        except Exception:
            self.message = 'Taught return stopped. Inspect Developer details before another attempt.'
            grant['status'] = 'stopped_or_failed'
            raise
        finally:
            permission_path.write_text(json.dumps(grant,indent=2),encoding='utf-8')

    def stop(self):
        run = self.get_runner()
        if run.active and run.name == 'recorded_return':
            run.request_stop()
        return dict(ok=True,message=('Stop requested. The queue monitor will stop the controller program; no automatic resume.'
                    if self.executor == 'lua_queue' else 'Stop requested. The current short movement finishes first.'))
