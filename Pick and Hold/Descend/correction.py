"""Fixed taught endpoint correction, executed at hover before pure-Z descent."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from autonomy import AlignmentGuard, TransferError, alignment_plan, check_path, ensure_arrival, number, wrap
from pick_and_hold.Descend.lua_executor import make_plan

PROFILE = Path(__file__).with_name('corrected_endpoint.json')
ROOT = Path(__file__).resolve().parents[2]


def corrected_plan(start, joints, target, cfg, envelope, band, *, profile_path=None):
    # Explicit path is for offline candidate validation; runtime uses PROFILE.
    raw=(PROFILE if profile_path is None else Path(profile_path)).read_bytes()
    profile=json.loads(raw)
    if profile.get('enabled') is not True or profile.get('frame')!='robot_base_mm_degrees':
        raise TransferError('The taught descent correction is unavailable.')
    if target.get('config')!='Wide':
        raise TransferError('The taught descent correction requires Wide two-disk calibration.')
    evidence=(ROOT/profile['evidence']).resolve()
    if ROOT not in evidence.parents or hashlib.sha256(evidence.read_bytes()).hexdigest()!=profile['evidence_sha256']:
        raise TransferError('Saved descent correction evidence changed; developer review required.')
    goal={key:number(profile['endpoint'][key],key) for key in ('X','Y','Z','Rz')}
    if 'vision_reference_z_mm' in profile:
        reviewed=json.loads(evidence.read_bytes())
        if reviewed.get('endpoint')!=goal or reviewed.get('vision_reference_z_mm')!=profile['vision_reference_z_mm']:
            raise TransferError('Taught endpoint/vision reference differs from its reviewed evidence.')
    height=number(profile['correction_height_mm'],'correction height')
    if height<300 or start['Z']<height-.05:
        raise TransferError('Run Align to Z300 before the taught claw correction; no adjustment near the plate.')
    dx,dy=goal['X']-target['x'],goal['Y']-target['y']
    xy = math.hypot(dx,dy)
    yaw = abs(wrap(goal['Rz']-target['rz']))
    # A reviewed manual endpoint can be higher than the vision reference.
    # Preserve the original vision-height acceptance band instead of widening it.
    depth_reference = number(profile.get('vision_reference_z_mm', goal['Z']), 'vision reference height')
    depth = abs(depth_reference-target['z_calibrated'])
    if (xy>number(profile['max_xy_correction_mm'],'XY correction limit') or
            yaw>number(profile['max_yaw_correction_deg'],'yaw correction limit') or
            depth>number(profile['max_depth_difference_mm'],'depth correction limit')):
        raise TransferError('Alignment is outside the taught plate region: '
                            f'vision differs from the saved reference by {xy:.1f} mm sideways, '
                            f'{yaw:.1f} degrees and {depth:.1f} mm in height. '
                            'Developer must check the camera reference and taught endpoint before descent.')
    # Still require the actual pose to match the fresh Align's XY/yaw.
    # Validate the taught depth we will execute, not the unused raw depth.
    make_plan(start,joints,{**target, 'z_calibrated':goal['Z']},cfg,envelope,band)
    corrected=deepcopy(target)
    corrected.update(x=goal['X'],y=goal['Y'],rz=goal['Rz'],z_calibrated=goal['Z'],z=goal['Z'],
                     descent_correction_id=profile['id'])
    legs=alignment_plan(start,corrected,joints,cfg,envelope,max(height,start['Z']),validate_descent=True)
    pose,q=deepcopy(start),dict(joints)
    for point in legs:
        q=check_path(pose,point,q,cfg,envelope);pose=dict(point)
    make_plan(pose,q,corrected,cfg,envelope,band)
    return dict(profile_id=profile['id'],profile_sha256=hashlib.sha256(raw).hexdigest(),
                start=deepcopy(start),original_target=deepcopy(target),target=corrected,legs=legs,hover=pose,
                endpoint=goal,scope=profile['scope'])


def apply_correction(run, svc, plan, cfg):
    guard=AlignmentGuard(svc,run,cfg)
    run.audit('descent_correction_plan',plan=plan)
    # Classify commanded legs against their planned predecessor, not another
    # encoder sample. The wrist service itself pins XYZ to its live reading.
    previous=plan['start']
    for point in plan['legs']:
        actual=guard.pose_mm()
        for key in ('X','Y','Z','Rz'):
            delta=number(actual.get(key),key)-previous[key]
            if key=='Rz':delta=wrap(delta)
            if abs(delta)>.05:
                raise TransferError('Arm moved from the correction waypoint; run Align again.')
        if abs(wrap(point['Rz']-previous['Rz']))>1e-6:
            if any(abs(point[k]-previous[k])>1e-6 for k in ('X','Y','Z')):
                raise TransferError('Correction rotation must hold XYZ fixed.')
            run.say('Adjusting claw angle above the plate.')
            guard.rotate_to_rz(point['Rz'])
        else:
            run.say('Centering claws above the plate.')
            guard.move_cartesian(point['X'],point['Y'],point['Z'],point['Rz'],5,'linear')
        ensure_arrival(guard.pose_mm(),point)
        previous=point
    ensure_arrival(guard.pose_mm(),plan['hover'])
    run.audit('descent_correction_complete',pose_mm=svc.pose_mm(),profile_id=plan['profile_id'])
