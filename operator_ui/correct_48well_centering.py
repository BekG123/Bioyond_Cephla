"""Restore accepted XY and retain accepted lower Z. No hardware access.

The rejected camera-derived forward vector is deliberately not reversed or
reapplied. A new longitudinal adjustment needs a verified physical direction.
"""
import json
import time
from copy import deepcopy
import projected_pickup as p
from autonomy import check_path

FOLDER = p.ROOT / 'operator_ui/reports/projected_alignment'
REJECTED = '5ee409d1c6b2ea7ffc59119fffa543e9b4918747996681d366b2a6cf9241c85a'
BASELINE = 'f3932615fca0640033099d35726290317cfee7f8e1658ff3aaed42ff01f13075'


def save(name, data):
    path = FOLDER / name
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2)
    return path.relative_to(p.ROOT).as_posix(), p.sha(path.read_bytes())


def main():
    rejected, digest = p.load()
    if digest != REJECTED:
        raise p.TransferError('Profile changed; do not apply a cumulative correction.')
    baseline_path = FOLDER / 'profile_before_forward_lower_20261027.json'
    baseline, baseline_digest = p.load(baseline_path)
    if baseline_digest != BASELINE:
        raise p.TransferError('Accepted centering reference changed.')
    goal = deepcopy(baseline['candidate_endpoint'])
    goal['Z'] = 73.718
    hover = {k: goal[k] for k in ('X', 'Y', 'Rz')}
    hover['Z'] = 300.
    trial = json.loads((FOLDER / 'forward_lower_full_trial_20261027.json').read_bytes())
    state = trial['state']
    cfg = json.loads((p.ROOT / 'operator_ui/robot_params.json').read_bytes())
    env = {k: (state['envelope'][k]['min'], state['envelope'][k]['max']) for k in ('X', 'Y', 'Z')}
    # Offline feasibility from recorded telemetry, not authorization to execute.
    pose, joints = state['robot']['pose_mm'], state['robot']['joints']
    legs = [dict(pose, Z=300.), hover, goal]
    for endpoint in legs:
        joints = check_path(pose, endpoint, joints, cfg, env)
        pose = endpoint
    backup, backup_hash = save('rejected_forward_lower_profile_20261027.json', rejected)
    feedback, feedback_hash = save('centering_restoration_feedback_20261027.json', dict(
        at=time.time(), rejected_profile=backup, rejected_profile_sha256=backup_hash,
        operator_feedback='10 mm forward was in the wrong direction; jaw gaps became uneven; lower height was correct.',
        source_centering_profile=baseline_path.relative_to(p.ROOT).as_posix(),
        source_centering_sha256=baseline_digest, accepted_gaps_mm=[25, 25],
        height_accepted_mm=73.718, candidate_endpoint=goal,
        forward_adjustment_applied_mm=0., forward_adjustment_pending_mm=10.,
        forward_direction_status='unresolved_physical_axis; rejected camera direction must not be reused',
        offline_ik_passed=True, recorded_start=state['robot']['pose_mm'], reviewed_legs=legs,
        physical_clearance_verified=False, motion_started=False, combined_endpoint_verified=False))
    approval, approval_hash = save('centering_restoration_trial_authorization_20261027.json', dict(
        visual_alignment_accepted=False, supervised_open_claw_trial_authorized=True,
        alignment_pose_mm=hover, operator_request='Correct this: restore accepted centering and retain accepted lower height.',
        feedback=feedback, feedback_sha256=feedback_hash, descent_accepted=False, grip_verified=False))
    candidate = deepcopy(baseline)
    for key in ('descent_acceptance', 'descent_acceptance_sha256'):
        candidate.pop(key, None)
    candidate.update(acceptance=approval, acceptance_sha256=approval_hash,
        alignment_pose_mm=hover, candidate_endpoint=goal,
        descent_status='pending_supervised_open_claw_trial',
        candidate_z_basis='Z73.718 accepted by operator in rejected-XY trial; combined restored-XY/lower-Z endpoint awaits inspection.',
        previous_profile=backup, previous_profile_sha256=backup_hash,
        correction_feedback=feedback, correction_feedback_sha256=feedback_hash,
        forward_along_plate_long_edge_mm=0., forward_adjustment_pending_mm=10.,
        additional_down_mm=5., physical_grip_validated_for_plate=False,
        automatic_lift_enabled=False, full_pickup_verified=False)
    saved, _ = save('restored_centering_lower_candidate_20261027.json', candidate)
    p.load(p.ROOT / saved)
    temp = p.PROFILE.with_suffix('.tmp')
    temp.write_bytes((p.ROOT / saved).read_bytes())
    temp.replace(p.PROFILE)
    print(json.dumps(dict(endpoint=goal, forward_pending_mm=10, offline_ik_passed=True,
                         motion_started=False, feedback=feedback)))


if __name__ == '__main__':
    main()
