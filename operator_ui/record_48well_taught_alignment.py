"""Record the operator's raised alignment; retain Z73.718 for descent.

Reads the existing console only. No hardware commands or controller preparation.
"""
import json
import time
from copy import deepcopy
from urllib.request import urlopen
from unittest.mock import patch
import projected_pickup as p
from autonomy import check_path, number, wrap
from correct_48well_centering import save


def main():
    old, digest = p.load()
    if digest != '7a6b065a536254e0f2b9ad6512267a144bd22f08f44c4b4b93b03603589a509a':
        raise p.TransferError('Source profile changed; review before replacing the taught reference.')
    samples = []
    expected = dict(X=308.971, Y=-64.539, Z=107.079, Rz=89.439)
    for _ in range(3):
        with urlopen('http://127.0.0.1:5002/state', timeout=8) as response:
            state = json.load(response)
        robot = state['robot']
        if not robot.get('connected') or not robot.get('ok') or state['sequence']['active']:
            raise p.TransferError('A connected idle robot is required to record the teaching.')
        actual = robot['pose_mm']
        if (any(abs(number(actual[k], k)-expected[k]) > .1 for k in ('X','Y','Z'))
                or abs(wrap(number(actual['Rz'], 'Rz')-expected['Rz'])) > .1):
            raise p.TransferError('Teaching pose changed; capture the new position explicitly.')
        samples.append(state)
        time.sleep(.15)
    observed = deepcopy(robot['pose_mm'])
    endpoint = dict(observed, Z=73.718)
    hover = {k: endpoint[k] for k in ('X', 'Y', 'Rz')}
    hover['Z'] = 300.
    backup, backup_sha = save('profile_before_manual_alignment_20261027.json', old)
    recording, recording_sha = save('manual_alignment_teaching_20261027.json', dict(
        at=time.time(), operator_feedback='Current raised position is the correct alignment; do not use its height for descent.',
        samples=samples, observed_pose_mm=observed, taught_components=['X','Y','Rz'],
        ignored_teaching_height_mm=observed['Z'], retained_descent_height_mm=73.718,
        candidate_endpoint=endpoint, reference_hover=hover,
        previous_profile=backup, previous_profile_sha256=backup_sha,
        replaces_inferred_forward_and_lateral_offsets=True,
        endpoint_visually_accepted_at_descent_height=False, motion_started=False))
    approval, approval_sha = save('manual_alignment_acceptance_20261027.json', dict(
        visual_alignment_accepted=True, alignment_pose_mm=hover,
        observation_pose_mm=observed, accepted_components=['X','Y','Rz'],
        teaching_record=recording, teaching_record_sha256=recording_sha,
        descent_accepted=False, grip_verified=False))
    candidate = deepcopy(old)
    for key in ('descent_acceptance', 'descent_acceptance_sha256',
                'additional_outward_correction', 'additional_outward_correction_sha256',
                'outward_correction_already_applied', 'inward_correction_already_applied',
                'total_outward_correction_mm', 'forward_along_plate_long_edge_mm',
                'forward_adjustment_pending_mm', 'correction_feedback', 'correction_feedback_sha256'):
        candidate.pop(key, None)
    candidate.update(acceptance=approval, acceptance_sha256=approval_sha,
        alignment_pose_mm=hover, candidate_endpoint=endpoint,
        descent_status='pending_supervised_open_claw_trial',
        candidate_z_basis='Retain operator-accepted Z73.718; raised teaching Z107.079 is not the descent height.',
        alignment_source='absolute operator-taught X/Y/Rz, replacing inferred offsets for this plate placement',
        manual_alignment=recording, manual_alignment_sha256=recording_sha,
        previous_profile=backup, previous_profile_sha256=backup_sha,
        physical_grip_validated_for_plate=False, automatic_lift_enabled=False, full_pickup_verified=False)
    saved, saved_sha = save('manually_aligned_pickup_candidate_20261027.json', candidate)
    loaded, loaded_sha = p.load(p.ROOT / saved)
    cfg = json.loads((p.ROOT / 'operator_ui/robot_params.json').read_bytes())
    env = {k: (state['envelope'][k]['min'], state['envelope'][k]['max']) for k in ('X','Y','Z')}
    joints = check_path(observed, hover, robot['joints'], cfg, env)
    with patch.object(p, 'load', return_value=(loaded, loaded_sha)):
        plan = p.descent_plan(hover, joints, p.target(trial=True), cfg, env, 66)
    save('manual_alignment_offline_review_20261027.json', dict(
        candidate_profile=saved, candidate_profile_sha256=saved_sha,
        offline_ik_passed=True, descent_plan=plan, motion_started=False,
        live_descent_verified=False))
    temp = p.PROFILE.with_suffix('.tmp')
    temp.write_bytes((p.ROOT / saved).read_bytes())
    temp.replace(p.PROFILE)
    print(json.dumps(dict(recording=recording, observed=observed,
        saved_endpoint=endpoint, offline_ik_passed=True, motion_started=False)))


if __name__ == '__main__':
    main()
