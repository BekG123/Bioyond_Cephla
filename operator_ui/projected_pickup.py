"""Plate-specific adapter to the existing ResearcherDescent and ReferenceGrip.

An accepted alignment does not certify a gripping height. A separate open-claw
trial and operator acceptance are required before this plate can prepare Grip.
No controller enable/reset, motion, or receipt restoration occurs on import.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
from autonomy import TransferError, ensure_arrival, number, alignment_plan, check_path
from researcher_teaching import TeachingError
from pick_and_hold.Descend.lua_executor import make_plan

ROOT=Path(__file__).resolve().parents[1]
PROFILE=ROOT/'Pick and Hold/Calibration/plate_48_pickup_profile.json'
PLATE_ID='48_well_projected_20261026'

def sha(raw):return hashlib.sha256(raw).hexdigest()

def evidence(path,digest):
    resolved=(ROOT/path).resolve()
    if ROOT not in resolved.parents or sha(resolved.read_bytes())!=digest:
        raise TransferError('48-well pickup evidence changed; review required.')
    return resolved


def accepted_grip(profile):
    if not profile.get('accepted_grip_reference'):
        return None
    path=evidence(profile['accepted_grip_reference'],profile['accepted_grip_reference_sha256'])
    reference=json.loads(path.read_bytes())
    if (reference.get('plate_profile_id')!=PLATE_ID
            or reference.get('status')!='operator_accepted_supervised_closure_and_loaded_home_transfer'
            or reference.get('plate_retained_during_lift_and_home_operator_confirmed') is not True
            or reference.get('taught_endpoint')!=profile['candidate_endpoint']
            or reference.get('settings',{}).get('target_e1_mm')!=3.9
            or reference['settings'].get('closing_speed')!=5
            or reference.get('force_control') is not False):
        raise TransferError('Accepted 48-well grip reference does not match this pickup.')
    for item in reference['evidence']:
        evidence(item['path'],item['sha256'])
    return reference

def load(profile_path=None):
    raw=(PROFILE if profile_path is None else Path(profile_path)).read_bytes();p=json.loads(raw)
    if p.get('id')!=PLATE_ID:raise TransferError('Unknown plate pickup profile.')
    accepted=json.loads(evidence(p['acceptance'],p['acceptance_sha256']).read_bytes())
    # A supervised open-claw trial is distinct from visual acceptance. Its
    # authorization must be pinned in evidence; normal Descent/Grip remain
    # blocked until the successful endpoint is separately accepted below.
    if not (accepted.get('visual_alignment_accepted') is True or
            accepted.get('supervised_open_claw_trial_authorized') is True):
        raise TransferError('48-well alignment has not been visually accepted.')
    if p['alignment_pose_mm']!=accepted['alignment_pose_mm']:
        raise TransferError('48-well alignment profile differs from accepted evidence.')
    expected=dict(p['alignment_pose_mm'])
    if p.get('lateral_correction'):
        correction=json.loads(evidence(p['lateral_correction'],p['lateral_correction_sha256']).read_bytes())
        source=correction['source_endpoint'];goal=correction['candidate_endpoint']
        if (correction.get('operator_direction_confirmed') is not True
                or correction.get('direction')!='toward_robot_base'
                or any(source[k]!=expected[k] for k in ('X','Y','Rz'))
                or goal!=p['candidate_endpoint'] or goal['Z']!=source['Z'] or goal['Rz']!=source['Rz']):
            raise TransferError('Invalid reviewed lateral correction.')
        cfg=json.loads(evidence(correction['robot_params'],correction['robot_params_sha256']).read_bytes())
        computed=inward_endpoint(source,cfg,2.)
        if any(abs(computed[k]-goal[k])>1e-8 for k in ('X','Y','Z','Rz')):
            raise TransferError('Lateral correction does not match the reviewed 2 mm base direction.')
        expected=goal
    for key in ('X','Y','Rz'):
        if p['candidate_endpoint'][key]!=expected[key]:
            raise TransferError('48-well endpoint differs from its accepted alignment/correction evidence.')
    evidence(p['alignment_log'],p['alignment_log_sha256'])
    evidence(p['parent_descent'],p['parent_descent_sha256'])
    if p['descent_status']=='operator_accepted_open_claw_descent':
        approval=json.loads(evidence(p['descent_acceptance'],p['descent_acceptance_sha256']).read_bytes())
        if approval.get('endpoint')!=p['candidate_endpoint'] or approval.get('visually_accepted') is not True:
            raise TransferError('48-well descent acceptance does not match its endpoint.')
    return p,sha(raw)

def inward_endpoint(source,cfg,distance=2.):
    """Absolute displacement from the recorded endpoint; never cumulative."""
    if number(distance,'inward distance')!=2.:raise TransferError('Only the reviewed 2 mm correction is supported.')
    goal={k:number(source[k],k) for k in ('X','Y','Z','Rz')}
    dx=number(cfg['base_x_mm'],'base X')-goal['X']
    dy=number(cfg['base_y_mm'],'base Y')-goal['Y']
    radius=math.hypot(dx,dy)
    if radius<=distance:raise TransferError('Invalid base-directed correction.')
    goal.update(X=goal['X']+distance*dx/radius,Y=goal['Y']+distance*dy/radius)
    return goal

def target(trial=False):
    p,digest=load()
    if p['descent_status']!='operator_accepted_open_claw_descent' and not trial:
        raise TransferError('48-well gripping height needs an open-claw trial and visual acceptance before Descent/Grip.')
    e=p['candidate_endpoint']
    return dict(x=number(e['X'],'X'),y=number(e['Y'],'Y'),rz=number(e['Rz'],'yaw'),
        z_calibrated=number(e['Z'],'candidate gripping height'),config='Wide',
        plate_profile_id=PLATE_ID,plate_profile_sha256=digest,open_claw_trial=bool(trial))

def descent_plan(start,joints,t,cfg,envelope,band):
    p,digest=load()
    if t.get('plate_profile_id')!=PLATE_ID or t.get('plate_profile_sha256')!=digest:
        raise TransferError('48-well descent profile changed after planning.')
    expected=target(trial=t.get('open_claw_trial') is True)
    if t!=expected:raise TransferError('48-well descent target differs from its reviewed profile.')
    hover={**p['candidate_endpoint'],'Z':300.}
    try:ensure_arrival(start,p['alignment_pose_mm'])
    except TransferError:ensure_arrival(start,hover)
    if start['Z']<299.95:raise TransferError('48-well descent must start at its accepted Z300 alignment.')
    legs=alignment_plan(start,t,joints,cfg,envelope,300.,validate_descent=True)
    pose,q=deepcopy(start),dict(joints)
    for point in legs:
        q=check_path(pose,point,q,cfg,envelope);pose=dict(point)
    make_plan(pose,q,t,cfg,envelope,band)
    return dict(profile_id=PLATE_ID,profile_sha256=digest,start=deepcopy(start),
        original_target=deepcopy(t),target=deepcopy(t),legs=legs,hover=pose,
        endpoint=deepcopy(p['candidate_endpoint']),scope='Current accepted 48-well placement only.',
        open_claw_trial=t['open_claw_trial'])


class ProjectedPickup:
    def __init__(self,descent,grip,service,runner,params,band):
        self.descent,self.grip,self.service,self.runner=descent,grip,service,runner
        self.params,self.band=params,band

    def public(self):
        try:
            p,digest=load()
            approval=json.loads(evidence(p['acceptance'],p['acceptance_sha256']).read_bytes())
            return dict(ok=True,plate_profile_id=PLATE_ID,
                calibration_alignment_accepted=bool(approval.get('visual_alignment_accepted') or
                    p['descent_status']=='operator_accepted_open_claw_descent'),
                profile_sha256=digest,
                descent_status=p['descent_status'],candidate_endpoint=p['candidate_endpoint'],
                candidate_height_verified=p['descent_status']=='operator_accepted_open_claw_descent',
                grip_method='existing staged ReferenceGrip',grip_target_e1_mm=3.9 if accepted_grip(p) else 3.7,
                automatic_lift_enabled=False,full_pickup_verified=False,
                blocker='' if p['descent_status']=='operator_accepted_open_claw_descent' else
                    '48-well gripping height needs an open-claw trial and visual acceptance.')
        except (OSError,ValueError,KeyError,TransferError) as error:
            return dict(ok=False,blocker=str(error))

    def start_trial(self,body):
        if any(body.get(k) is not True for k in ('ready','empty_gripper','cell_clear','plate_unchanged')):
            raise TeachingError('Confirm unchanged plate, empty jaws, clear descent path, hands clear and E-stop supervision.',400)
        run,svc=self.runner(),self.service()
        if run.active or getattr(run,'reserved',False):raise TeachingError('Another action is running.')
        status=svc.status()
        if not status.get('connected') or not status.get('ok') or status.get('errors'):
            raise TeachingError('Healthy connected robot required; no fault reset or motion was requested.')
        t=target(trial=True);pose=svc.pose_mm()
        if body.get('expected_profile_sha256')!=t['plate_profile_sha256']:
            raise TeachingError('The descent trial profile changed; review its endpoint again.')
        if not svc.envelope_enabled:raise TeachingError('The descent workspace must be enabled.')
        plan=descent_plan(pose,svc.joints(),t,self.params(),svc.envelope,self.band())
        # The existing executor verifies opening to 28 mm before Lua descent.
        # Trial completion deliberately does not issue a Grip receipt.
        self.grip.invalidate()
        return run.start('researcher_descend',self.descent.execute,svc,t,pose,plan)

    def accept_descent(self,body):
        if body.get('visually_accepted') is not True:
            raise TeachingError('Confirm both jaws are centered, clear and at the intended gripping height.',400)
        run,svc=self.runner(),self.service();p,digest=load()
        result=deepcopy(run.result or {})
        if (run.active or run.name!='researcher_descend' or run.state!='done'
                or not result.get('ok') or not result.get('open_claw_trial')
                or result.get('plate_profile_id')!=PLATE_ID
                or result.get('descent_correction',{}).get('profile_sha256')!=digest):
            raise TeachingError('A successful current 48-well open-claw descent trial is required.')
        pose=svc.pose_mm();ensure_arrival(pose,p['candidate_endpoint'])
        status=svc.status()
        if not status.get('connected') or not status.get('ok') or status.get('errors'):
            raise TeachingError('Healthy controller feedback required before accepting descent.')
        if not 27.98<=number(svc.external_axes().get('E1'),'claw position')<=28.05:
            raise TeachingError('Claw must remain fully open after the trial.')
        approval=dict(visually_accepted=True,at=time.time(),endpoint=p['candidate_endpoint'],
            source_profile_sha256=digest,result=result,run_id=run.run_id)
        folder=ROOT/'operator_ui/reports/projected_alignment'
        path=folder/('descent_accepted_'+str(time.time_ns())+'.json')
        path.write_text(json.dumps(approval,indent=2),encoding='utf-8')
        p.update(descent_status='operator_accepted_open_claw_descent',
            descent_acceptance=path.relative_to(ROOT).as_posix(),descent_acceptance_sha256=sha(path.read_bytes()))
        temp=PROFILE.with_suffix('.tmp');temp.write_text(json.dumps(p,indent=2),encoding='utf-8');temp.replace(PROFILE)
        self.grip.completed_descent(result,pose)
        return dict(ok=True,message='48-well descent accepted. Grip is available; no closing or lift started.')

    def grip_configuration(self,context,reference,base_digest):
        result=context.get('descent_result',context)
        if result.get('plate_profile_id')!=PLATE_ID:
            raise TeachingError('Unknown projected plate grip context.')
        p,digest=load()
        if p['descent_status']!='operator_accepted_open_claw_descent':
            raise TeachingError('Accept the open-claw 48-well descent before Grip.')
        plan=result.get('descent_correction',{})
        if plan.get('endpoint')!=p['candidate_endpoint']:
            raise TeachingError('Descent does not match the accepted 48-well endpoint.')
        if plan.get('profile_sha256')!=digest:
            approval=json.loads(evidence(p['descent_acceptance'],p['descent_acceptance_sha256']).read_bytes())
            if result!=approval['result']:
                raise TeachingError('Projected descent receipt is stale or changed.')
        adapted=deepcopy(reference)
        adapted['closure']['pose_mm_degrees']=deepcopy(p['candidate_endpoint'])
        adapted['plate_profile_id']=PLATE_ID
        adapted['physical_grip_validated_for_plate']=False
        grip=accepted_grip(p)
        if grip:
            adapted['settings'].update(target_e1_mm=3.9,closing_speed=5)
            adapted['accepted_plate_grip']=True
            adapted['physical_grip_validated_for_plate']=True
        return adapted,sha((base_digest+digest).encode())
