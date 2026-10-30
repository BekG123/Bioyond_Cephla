"""48-well button integration using the reviewed observation and pickup routines.

Reuses the accepted absolute endpoint only when fresh plate measurements agree
with its pinned raw alignment. Never adapts the taught endpoint automatically.
"""
from copy import deepcopy
import json
import math
import time

from autonomy import GuardedService, TransferError, check_path, ensure_arrival, wrap
from researcher_teaching import TeachingError
from classic_pickup import ClassicPickup, TRANSPORT_STEPS
import projected_pickup as pickup


STEPS = (
    ('Calibrate', 'plate48_calibrate', 'Calibrate the 48-well plate'),
    ('Align', 'projected_alignment', 'Align with the 48-well plate'),
    ('Descend', 'researcher_descend', 'Descend to the taught 48-well position'),
    ('Grip', 'position_grip', 'Grip the 48-well plate'),
)
REQUIREMENTS = [
    'Start at saved Home with empty jaws. The 48-well plate is flat in its accepted holder and orientation.',
    'Keep the same plate support and camera settings as the reviewed 48-well setup.',
    'Confirm the lift to the observation height, alignment sweep, descent, and loaded Home route are clear; supervise the emergency stop.',
    'Uses well-grid detection and the verified height reference, then the taught descent and accepted 3.9 mm grip.',
    'After gripping, lift 5 mm slowly and return Home with the claw unchanged. Changed plate placement stops for review.',
]


def match_placement(actual, expected):
    if not all(math.isfinite(value[key]) for value in (actual, expected) for key in ('x', 'y', 'rz')):
        raise TransferError('48-well placement measurement is not finite.')
    if (math.hypot(actual['x']-expected['x'], actual['y']-expected['y']) > .5
            or abs(wrap(actual['rz']-expected['rz'])) > .2):
        raise TransferError('48-well plate placement changed. Review or reteach before reusing its descent; no automatic endpoint adjustment.')


def reference():
    profile, digest = pickup.load()
    approval = json.loads(pickup.evidence(profile['acceptance'], profile['acceptance_sha256']).read_bytes())
    raw = approval.get('fresh_alignment', {}).get('route', {}).get('target')
    if not raw:
        raise TransferError('Accepted 48-well raw alignment reference is missing.')
    if profile['descent_status'] != 'operator_accepted_open_claw_descent' or not pickup.accepted_grip(profile):
        raise TransferError('48-well descent and grip acceptance are required for this workflow.')
    return profile, digest, raw


class Plate48Teaching:
    def __init__(self, service, runner, camera, params, prepare, home, invalidate, band):
        self.service, self.runner, self.camera = service, runner, camera
        self.params, self.prepare, self.home, self.invalidate = params, prepare, home, invalidate
        self.band = band
        self.context = None

    def start(self, action, body):
        if body.get('ready') is not True or action not in ('Calibrate', 'Align'):
            raise TeachingError('Confirm the empty gripper, unchanged 48-well setup and clear route.', 400)
        run, svc = self.runner(), self.service()
        if run.active or (run.reserved and not run.owns_reservation):
            raise TeachingError('Another workflow owns the arm.')
        state = svc.status()
        if not state.get('connected') or not state.get('ok') or state.get('errors') or not svc.envelope_enabled:
            raise TeachingError('Healthy connected controller and enabled workspace required. No fault reset requested.')
        reference()
        if action == 'Calibrate':
            ensure_arrival(svc.pose_mm(), self.home.target()[0])
            self.context = None
            self.invalidate()
            return run.start('plate48_calibrate', self.calibrate)
        context = deepcopy(self.context)
        if not context or not 0 <= time.time()-context['at'] <= 600:
            raise TeachingError('Run 48-well calibration first; its observation has expired or is missing.')
        if run.run_id != context['run_id'] or run.name != 'plate48_calibrate' or not (run.result or {}).get('ok'):
            raise TeachingError('Run 48-well calibration again after any intervening sequence.')
        ensure_arrival(svc.pose_mm(), context['pose'])
        if reference()[1] != context['profile_sha256']:
            raise TeachingError('48-well profile changed after calibration.')
        return run.start('projected_alignment', self.align, context)

    def calibrate(self, run):
        from projected_alignment import perception_at_height, target_from_mark, plan
        from projected_disk_trial import stationary_observation
        svc = self.service()
        run.target = None
        try:
            profile, digest, raw = reference()
            p, height, provenance = perception_at_height()
            # Same observation entry used by repeat_taught_48well.py.
            home = dict(X=289.97, Y=62.63, Z=248.02, Rz=-3.88)
            ensure_arrival(self.home.target()[0], home)
            ensure_arrival(svc.pose_mm(), home)
            if abs(height['observation_z_mm']-289.129) > .001:
                raise TransferError('48-well observation height changed; review the entry route.')
            points = [dict(home, Z=289.129), dict(X=279.303,Y=26.358,Z=289.129,Rz=-3.88)]
            pose, q = svc.pose_mm(), svc.joints()
            for point in points:
                q = check_path(pose, point, q, self.params(), svc.envelope)
                pose = point
            if not self.camera().info().get('enabled'):
                raise TransferError('Connect the camera before 48-well calibration.')
            self.camera().snap()
            self.prepare(run, svc)
            guard = GuardedService(svc, run, self.params())
            guard._preflight()
            ensure_arrival(guard.pose_mm(), home)
            for point in points:
                run.say('Moving to the reviewed 48-well observation position at speed 5.')
                guard.move_cartesian(point['X'],point['Y'],point['Z'],point['Rz'],5,'linear')
                ensure_arrival(guard.pose_mm(), point)
            def record(event, **fields): run.audit('plate48_'+event, **fields)
            targets=[]
            for _ in range(3):
                pose, measurement = stationary_observation(guard,self.camera(),p,record)
                if math.hypot(*measurement['error_xy_mm']) > .75:
                    raise TransferError('48-well plate is outside the reviewed centering tolerance; reposition/review before continuing.')
                target = target_from_mark(pose,measurement,p.cfg)
                match_placement(target,raw)
                for previous in targets: match_placement(target,previous)
                targets.append(target)
            route = plan(pose,measurement,p.cfg,svc.joints(),self.params(),svc.envelope)
            # Validate alignment, the accepted non-cumulative correction, and descent before publishing.
            q=svc.joints(); current=pose
            for point in route['waypoints']+[profile['alignment_pose_mm']]:
                q=check_path(current,point,q,self.params(),svc.envelope);current=point
            pickup.descent_plan(current,q,pickup.target(),self.params(),svc.envelope,self.band())
            if reference()[1] != digest: raise TransferError('48-well profile changed during calibration.')
            self.context=dict(at=time.time(),run_id=run.run_id,pose=pose,expected_target=route['target'],
                              profile_sha256=digest,reference=provenance)
            run.say('48-well calibration verified against the taught placement. Alignment is ready.','good')
            return dict(ok=True,plate_profile_id=pickup.PLATE_ID,calibration_complete=True,
                        target=route['target'],context=deepcopy(self.context))
        except Exception as error:
            self.context=None
            run.state='stopped' if run.stopped() else 'error'
            run.say(str(error),'err')
            return dict(ok=False,error=str(error))

    def align(self, run, context):
        from projected_alignment import align
        svc=self.service()
        try:
            profile,digest,raw=reference()
            if digest != context['profile_sha256']: raise TransferError('48-well profile changed before alignment.')
            result=align(run,svc,self.camera(),self.params(),dict(
                expected_start=context['pose'],expected_target=context['expected_target']))
            if not result.get('ok'): return result
            match_placement(result['route']['target'],raw)
            guard=GuardedService(svc,run,self.params())
            point=profile['alignment_pose_mm']
            check_path(guard.pose_mm(),point,svc.joints(),self.params(),svc.envelope)
            run.say('Applying the accepted absolute jaw alignment; no cumulative offset.')
            guard.move_cartesian(point['X'],point['Y'],point['Z'],point['Rz'],5,'linear')
            ensure_arrival(guard.pose_mm(),point)
            if reference()[1] != digest: raise TransferError('48-well profile changed during alignment.')
            run.target=pickup.target()
            result.update(plate_profile_id=pickup.PLATE_ID,profile_sha256=digest,
                          accepted_hover=deepcopy(point),visual_acceptance_pending=False)
            return result
        except Exception as error:
            run.state='stopped' if run.stopped() else 'error'
            run.say(str(error),'err')
            return dict(ok=False,error=str(error))
        finally:
            self.context=None


class Plate48Pickup(ClassicPickup):
    requirements = REQUIREMENTS

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.steps = STEPS + TRANSPORT_STEPS if self.transport else STEPS

    def _draft_body(self):
        reference()
        return dict(ready=True)

    def public(self):
        result=super().public()
        try: reference()
        except Exception as error: result.update(can_start=False,blocker=str(error))
        return result
