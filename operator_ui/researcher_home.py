"""Confirmed Home returns; IK plans can preserve an already-held plate."""
import hashlib
import json
import math
import time
from pathlib import Path

from autonomy import AlignmentGuard, TransferError, alignment_plan, ensure_arrival, check_path
from researcher_teaching import TeachingError, numbers
from imitation_agent import close_pose
from trajectory_queue import LuaTrajectory, prepare_points

HOME_SPEED = 137


def compact_home_connection(start, target, joints, params, envelope):
    """Three MoveL commands, with wrist interpolation only at clearance height."""
    height = max(300., start['Z']+20., target['Z']+20.)
    points = [{k:start[k] for k in ('X','Y','Z','Rz')}, dict(target), dict(target)]
    points[0]['Z'] = points[1]['Z'] = height
    points, _ = prepare_points(start,joints,points,params,reviewed=True,straight_transfer=True)
    q, previous = joints, start
    for point in points:
        q = check_path(previous,point,q,params,envelope)
        previous = point
    return points


def plan_station_route(start, target, joints, params, envelope):
    """Pure Home/Hamilton route planning; no controller calls or limit changes."""
    travel = max(300., start['Z'], target['Z'] + 20.)
    legs = alignment_plan(start, dict(x=target['X'], y=target['Y'], rz=target['Rz'], z_calibrated=target['Z']),
                          joints, params, envelope, travel, validate_descent=True)
    count = max(1, math.ceil((travel-target['Z'])/10))
    legs.extend({**target, 'Z': travel+(target['Z']-travel)*i/count} for i in range(1,count+1))
    return legs


def queued_station_stages(start, target, joints, params, envelope):
    """Validate the original Home route, then queue its straight translations."""
    if close_pose(start,target):
        return []
    original=plan_station_route(start,target,joints,params,envelope)
    height=max(300.,start['Z'],target['Z']+20.)
    current,q,stages=dict(start),joints,[]
    def queue(points):
        nonlocal current,q
        points,_=prepare_points(current,q,points,params,reviewed=True,home_transit=True)
        for point in points:
            q=check_path(current,point,q,params,envelope)
            current=point
        stages.append(dict(kind='queue',points=points))
    if height-current['Z']>.02:
        queue([{**current,'Z':height}])
    # Preserve the original planner's bounded wrist steps at clearance height.
    previous=start
    for point in original:
        rotation=all(abs(previous[k]-point[k])<.05 for k in ('X','Y','Z')) and abs(previous['Rz']-point['Rz'])>.02
        if rotation:
            rotated={**current,'Rz':point['Rz']}
            q=check_path(current,rotated,q,params,envelope)
            stages.append(dict(kind='rotate',rz=point['Rz']))
            current=rotated
        previous=point
    tail=[]
    if math.hypot(target['X']-current['X'],target['Y']-current['Y'])>.02:
        tail.append({**target,'Z':height})
    if abs(target['Z']-height)>.02:
        tail.append(dict(target))
    if tail:queue(tail)
    return stages


def home_route_error(error, start, params, envelope):
    """Explain a rejected route without changing its limits or proposing a bypass."""
    details = []
    reach = math.hypot(start['X']-params['base_x_mm'], start['Y']-params['base_y_mm'])
    maximum = params['link1_mm'] + params['link2_mm'] - params['extension_margin_mm'] - 2
    if reach > maximum:
        details.append(f'Current arm reach is {reach:.1f} mm; the automatic limit is {maximum:.1f} mm')
    elif reach < 20:
        details.append(f'Current arm reach is {reach:.1f} mm; it is inside the folded-arm exclusion zone')
    for axis, (low, high) in (envelope or {}).items():
        if axis in start and not low <= start[axis] <= high:
            details.append(f'{axis}={start[axis]:.1f} mm is outside the travel workspace ({low:g} to {high:g} mm)')
    if not details:
        details.append(str(error))
    return ('Automatic Home route blocked. ' + '; '.join(details) +
            '. Have the return route checked in Developer view, or use supervised hand-guiding along a verified clear route. No Home movement was started.')


class HomeReturn:
    def __init__(self, points_path, get_service, get_runner, get_draggo, params, invalidate, prepare=None):
        self.path = Path(points_path)
        self.get_service, self.get_runner, self.get_draggo = get_service, get_runner, get_draggo
        self.params, self.invalidate = params, invalidate
        self.prepare = prepare
        self.message = 'Return to your saved Home position.'
        self.hamilton_route = None
        self.queued_phase = False

    def target(self):
        data = json.loads(self.path.read_text(encoding='utf-8-sig'))
        point = data['points'][data['roles']['home']]
        target = numbers(dict(X=point['x'], Y=point['y'], Z=point['z_grip'], Rz=point['rz']), ('X','Y','Z','Rz'))
        ident = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()
        return target, ident

    def area_target(self):
        if not self.hamilton_route:
            raise TeachingError('The taught Home-area is unavailable.')
        point = self.hamilton_route.reviewed()[2]['start']
        return point, hashlib.sha256(json.dumps(point,sort_keys=True).encode()).hexdigest()

    def public(self, robot, hand):
        run = self.get_runner()
        active = run.active and run.name == 'researcher_home'
        ident, blocker = None, ''
        route_review = ''
        try:
            _, ident = self.target()
        except Exception:
            blocker = 'Save and assign a valid Home position in Developer view.'
        if not robot.get('connected'):
            blocker = 'Connect the robot in Prepare.'
        elif not robot.get('ok') or robot.get('errors'):
            blocker = 'Resolve the robot alert in Developer view.'
        elif hand.get('state') not in ('off','active'):
            blocker = 'Hand-guiding status needs attention. Resolve it before returning Home.'
        elif hand.get('state') == 'active' and self.prepare is None:
            blocker = 'End hand-guiding before returning Home.'
        elif robot.get('control_mode', {}).get('mode') not in ('manual','auto') or robot.get('program_state', {}).get('state') not in ('stopped','running','paused'):
            blocker = 'Controller mode or program status is unavailable.'
        elif self.prepare is None and (robot.get('control_mode', {}).get('mode') != 'auto' or not robot.get('enabled') or robot.get('program_state', {}).get('state') != 'running'):
            blocker = 'Enable Auto motion and the controller program in Developer view.'
        elif not self.get_service().envelope_enabled:
            blocker = 'Verify the travel workspace in Developer view.'
        elif run.active:
            blocker = 'Wait for the current movement to finish.'
        if not blocker and robot.get('pose_mm') and robot.get('joints'):
            # Use the existing telemetry snapshot: no controller calls or motion.
            start, params, envelope = robot['pose_mm'], self.params(), self.get_service().envelope
            try:
                target, _ = self.target()
                proposed=self.route_plan(start, target, robot['joints'], params, envelope)
                route_review=(proposed.get('prefix') or {}).get('requirement','')
            except TeachingError as error:
                blocker = str(error)
            except TransferError as error:
                blocker = home_route_error(error, start, params, envelope)
        area_id, can_area = None, False
        # Completion text is historical; hand-guiding may have moved the arm.
        # Derive "at Home" from the current snapshot, never the last job message.
        at_home = False
        if ident and robot.get('pose_mm'):
            try:
                at_home = close_pose(robot['pose_mm'], self.target()[0])
            except (KeyError, TypeError, ValueError, TeachingError):
                pass
        message = self.message
        if route_review and not active:
            message=route_review
        if message.startswith('At saved Home.') and (not at_home or blocker or active):
            message = 'Return to your saved Home position.'
        return dict(can_start=bool(ident and not blocker), active=active, target_id=ident,
                    at_home=at_home, message=message, blocker=blocker, can_go_to_area=can_area, area_target_id=area_id,translation_speed=HOME_SPEED)

    def start(self, body, *, approved_ik=None, before_dispatch=None):
        if body.get('ready') is not True:
            raise TeachingError('Confirm the saved Home and clear return route with an empty gripper.', 400)
        service = self.get_service()
        state = service.status()
        ready = self.public(state, self.get_draggo().public(state))
        if not ready['can_start']:
            raise TeachingError(ready['blocker'])
        target, ident = self.target()
        to_area = body.get('destination') == 'home_area'
        if to_area:
            raise TeachingError('Home-area is retired. Use true Home or the Hamilton routine.')
        if body.get('destination', 'home') != 'home':
            raise TeachingError('Choose saved Home.')
        if body.get('target_id') != ident:
            raise TeachingError('The Home position changed. Refresh and check it again.')
        refusal = service._preflight() if self.prepare is None else None
        if refusal:
            raise TeachingError('Robot is not ready for motion. Check Developer view.')
        # Validate the complete route before dispatching even the first lift.
        start = numbers(service.pose_mm(), ('X','Y','Z','Rz'))
        try:
            if approved_ik is not None:
                from ik_home import compare_snapshot
                from reviewed_home import ReviewedHomeConnection
                snapshot=service.status()
                compare_snapshot(approved_ik,snapshot,self.params(),{k:list(v) for k,v in service.envelope.items()},target,ident)
                if hashlib.sha256(self.path.read_bytes()).hexdigest()!=approved_ik['points_sha256']:
                    raise TeachingError('Saved positions changed after the Home preview.')
                stages=queued_station_stages(start,target,service.joints(),self.params(),service.envelope)
                if not ReviewedHomeConnection.same_stages(stages,approved_ik['stages']):
                    raise TeachingError('Home path changed after confirmation.')
                legs=dict(prefix=None,points=[],queued_connector=False,target=target,
                    stages=approved_ik['stages'],monitor_gripper=True,
                    preserve_e1=approved_ik['e1'] if approved_ik['preserve_gripper'] else None)
            else:
                legs = self.plan(service, start, target)
        except (TransferError, TeachingError) as error:
            self.message = str(error) if isinstance(error, TeachingError) else home_route_error(error, start, self.params(), service.envelope)
            raise TeachingError(self.message) from None
        if legs['prefix'] or legs.get('queued_connector') or legs.get('stages'):
            if self.hamilton_route and approved_ik is None:self.hamilton_route.check_previous_attempt()
            support = LuaTrajectory(service).capability()
            # An uninitialized program cannot advertise its queue version yet.
            # Only the normal, confirmed Auto preparation may initialize it;
            # execute() must then verify support before any Home movement.
            if not (self.prepare is not None and support.get('needs_initialization')):
                self.require_home_queue(support)
        self.invalidate()
        self.message = 'Returning Home. Keep hands clear.'
        if before_dispatch is not None:
            before_dispatch()
        result = self.get_runner().start('researcher_home', self.execute, service, start, target, legs)
        if not result.get('ok'):
            raise TeachingError('The arm is busy. Wait for the current action to finish.')
        return dict(ok=True, message=self.message)

    def plan(self, service, start, target):
        return self.route_plan(start, target, service.joints() or {}, self.params(), service.envelope)

    @staticmethod
    def require_home_queue(support):
        if not support.get('available'):
            raise TeachingError(support.get('message') or 'Could not verify the controller trajectory executor.')
        if support.get('max_speed_mm_s',0)<HOME_SPEED:
            raise TeachingError(f"The running queue supports {support.get('max_speed_mm_s',0):g}; Home requires the published speed-{HOME_SPEED:g} program.")

    def route_plan(self, start, target, joints, params, envelope):
        if self.hamilton_route:
            self.hamilton_route.check_previous_attempt()
            original,source_id,_=self.hamilton_route.reviewed()
            from hamilton_true_home import station_reference
            ham_pose,ham_q=station_reference(original)
            from hamilton_true_home import candidate,departure_start,measured_departure
            review = candidate(target,envelope)
            measured = measured_departure(start,review)
            if measured is not None:
                ham_pose,ham_q = measured['pose'],measured['joints']
            elif departure_start(start,review):
                ham_q['J1']+=start['Z']-ham_pose['Z']
                ham_pose={**ham_pose,'Z':start['Z']}
            first=dict(pose_mm=ham_pose,joints=ham_q)
            try:
                self.hamilton_route.match_start(start,joints,first)
                at_hamilton=True
            except TeachingError:
                at_hamilton=False
            if at_hamilton:
                from hamilton_true_home import candidate,check_route,requirement
                self.hamilton_route.check_previous_attempt()
                review=candidate(target,envelope)
                points=review['reverse'][1:]
                check_route(start,points,joints,params,envelope,review)
                prefix=dict(direct_true_home=True,points=points,endpoint=target,
                            path_id=hashlib.sha256(json.dumps(review,sort_keys=True).encode()).hexdigest(),
                            source_id=source_id,review=review,requirement=requirement(review))
                return dict(prefix=prefix,points=[],target=target,queued_connector=False,stages=[])
        return dict(prefix=None,points=[],target=target,queued_connector=False,
                    stages=queued_station_stages(start,target,joints,params,envelope))

    def execute(self, run, service, start, target, legs):
        plan = legs
        legs = plan['points']
        prefix = plan['prefix']
        attempt_path = None
        attempt = None
        preparing = False
        travel_dispatched = False
        try:
            if prefix and prefix.get('direct_true_home'):
                from ik_home import ready_auto
                from scope_compact137 import HoldingService
                if not ready_auto(service.status()):
                    raise TeachingError('Direct Hamilton/Home requires already-running Auto; no automatic preparation.')
                value=service.external_axes().get('E1')
                if type(value) not in (int,float) or not math.isfinite(value):
                    raise TeachingError('Claw feedback unavailable.')
                plan['preserve_e1']=value
                plan['monitor_gripper']=True
            if prefix or plan.get('queued_connector') or plan.get('stages'):
                folder=self.hamilton_route.attempts if self.hamilton_route else self.path.parent/'home_route_runs'
                folder.mkdir(parents=True, exist_ok=True)
                attempt_path = folder/f'{time.time_ns()}_saved_home.json'
                attempt = dict(status='attempt_started', path_id=prefix['path_id'] if prefix else None, target=target,
                    prefix=prefix, connector=legs if plan.get('queued_connector') else None,stages=plan.get('stages',[]),attempt_available=False, allow_explicit_repeats=False,
                    authorization='Return Home button with full-route readiness confirmation',
                    workspace_box_exception='Only the exact reviewed Hamilton departure' if prefix else False, speed=HOME_SPEED,connector_speed=HOME_SPEED)
                attempt_path.write_text(json.dumps(attempt,indent=2),encoding='utf-8')
            if plan.get('preserve_e1') is not None:
                from ik_home import ready_auto
                state=service.status()
                if not ready_auto(state) or not state.get('ok') or state.get('errors'):
                    raise TransferError('Controller readiness changed; no startup or gripper command sent.')
            elif self.prepare is not None:
                self.message = 'Preparing Auto motion for Home. Keep hands clear.'
                run.say(self.message)
                preparing = True
                self.prepare(run, service)
                preparing = False
            if plan.get('monitor_gripper'):
                from scope_compact137 import HoldingService
                held_e1=plan.get('preserve_e1')
                if held_e1 is None:
                    held_e1=service.external_axes().get('E1')
                if type(held_e1) not in (int,float) or not math.isfinite(held_e1):
                    raise TransferError('Claw position could not be verified before Home.')
                service=HoldingService(service,held_e1,{k:list(v) for k,v in service.envelope.items()})
            ensure_arrival(service.pose_mm(), start)
            if prefix or plan.get('queued_connector') or plan.get('stages'):
                self.require_home_queue(LuaTrajectory(service).capability())
            if prefix:
                travel_dispatched = True
                self.message = 'Following the taught Hamilton return, then finishing at saved Home.'
                self.queued_phase = True
                if prefix.get('direct_true_home'):
                    from hamilton_true_home import check_route
                    check_route(service.pose_mm(),prefix['points'],service.joints(),
                                self.params(),service.envelope,prefix['review'])
                    result=LuaTrajectory(service).execute(run,service.pose_mm(),service.joints(),
                        prefix['points'],self.params(),HOME_SPEED,
                        lambda stage,done,total:run.audit('hamilton_true_home_progress',
                            stage=stage,done=done,pose=service.pose_mm(),e1=service.external_axes()),
                        reviewed=True,hamilton_home=True,home_speed137=True)
                else:
                    result = self.hamilton_route.execute_home_prefix(run, service, prefix)
                self.queued_phase = False
                if not result.get('ok'):
                    raise TransferError('Hamilton departure did not finish; no Home connector started.')
                ensure_arrival(service.pose_mm(), prefix['endpoint'])
            guard = AlignmentGuard(service, run, self.params())
            guard._preflight()
            if plan.get('queued_connector'):
                travel_dispatched = True
                self.message = 'Following the three-point Home connection. Keep hands clear.'
                current, joints = service.pose_mm(), service.joints()
                for point in legs:
                    joints = check_path(current,point,joints,self.params(),service.envelope)
                    current = point
                self.queued_phase = True
                result = LuaTrajectory(service).execute(run,service.pose_mm(),service.joints(),legs,self.params(),HOME_SPEED,
                    lambda stage,done,total:run.say(f'Home connection: {stage} {done:.0f}/{total}'),
                    reviewed=True,straight_transfer=True,home_speed137=True)
                self.queued_phase = False
                if not result.get('ok'):
                    raise TransferError('The Home connection did not finish.')
            for stage in plan.get('stages',[]):
                guard._preflight()
                travel_dispatched = True
                if stage['kind']=='rotate':
                    self.message='Adjusting the wrist above Home. Keep hands clear.'
                    guard.rotate_to_rz(stage['rz'])
                else:
                    self.message='Moving Home. Keep hands clear.'
                    current,joints=service.pose_mm(),service.joints()
                    for point in stage['points']:
                        joints=check_path(current,point,joints,self.params(),service.envelope)
                        current=point
                    self.queued_phase=True
                    result=LuaTrajectory(service).execute(run,service.pose_mm(),service.joints(),stage['points'],self.params(),HOME_SPEED,
                        lambda phase,done,total:run.say(f'Home: {phase} {done:.0f}/{total}'),
                        reviewed=True,home_transit=True,home_speed137=True)
                    self.queued_phase=False
                    if not result.get('ok'):raise TransferError('Home transit did not finish.')
            guard._preflight()
            ensure_arrival(service.pose_mm(), target)
            self.message = 'At saved Home. Your teaching records are unchanged.'
            if attempt:
                attempt['status'] = 'completed'
            return dict(ok=True, home=target)
        except Exception as error:
            if attempt:
                attempt['status'] = 'stopped_or_failed'
            from home_attempts import ProgramStartRefused, HomeTravelNotStarted
            if preparing and not travel_dispatched and isinstance(error, ProgramStartRefused):
                refusal = HomeTravelNotStarted(error)
                if attempt is not None:
                    attempt['home_startup_refusal'] = refusal.evidence
                self.message = str(refusal)
                raise refusal from error
            self.message = 'Home return stopped. Check the arm and Developer details before retrying.'
            raise
        finally:
            self.queued_phase = False
            if attempt_path:
                attempt_path.write_text(json.dumps(attempt,indent=2),encoding='utf-8')

    def stop(self):
        run = self.get_runner()
        if run.active and run.name == 'researcher_home':
            run.request_stop()
            self.message = ('Stop requested. The queue monitor will stop the controller program.' if self.queued_phase else
                            'Stop requested. The current short movement finishes first.')
        return dict(ok=True, message=self.message)
