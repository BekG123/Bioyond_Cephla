"""Link operator-confirmed long-side pickup evidence; no hardware commands."""
import json
import time
from copy import deepcopy
from projected_pickup import ROOT, PROFILE, load, sha, accepted_grip

SOURCE_SHA = '446d252761215951c2e6ddbc46275998e129f21a9ed1b7333b99b7947954edf2'
TRIAL = ROOT/'operator_ui/reports/projected_alignment/accepted_y104_repeat_350f5ded2c2a4abbb61cc671fe09f0f5'
HOME = ROOT/'operator_ui/reports/squid_48well_approach/calibration_home_exchange_retry01_20261110'
OUT = ROOT/'operator_ui/reports/projected_alignment/long_side_y104_acceptance_20261110'
FEEDBACK = ('I confirm that the 10.4 mm is correct, so link and fix the issue. '
            'In fact, this coordinate is where the arm aligns with the long side '
            'of the plate nicely, so save the coordinate as such.')


def main():
    profile, digest = load()
    if digest != SOURCE_SHA:
        raise RuntimeError('Source profile changed; do not replace a newer acceptance.')
    paths = [TRIAL/'attempt.json', TRIAL/'grip_attempt.json', TRIAL/'proof_lift.json',
             HOME/'calibrated_home.json', HOME/'run.json',
             ROOT/profile['descent_acceptance']]
    descent, grip, lift, home, run, visual = [json.loads(p.read_bytes()) for p in paths]
    endpoint = profile['candidate_endpoint']
    assert descent['endpoint'] == grip['pose'] == visual['endpoint'] == endpoint
    assert all(v['profile_sha256'] == digest for v in (descent, grip, lift))
    assert descent['status'] == 'accepted_geometry_repeat_descent_complete'
    assert grip['status'] == 'closed_awaiting_operator_inspection'
    assert grip['target_e1_mm'] == 3.9 and grip['speed'] == 5
    assert lift['status'] == 'lift_completed_awaiting_visual_inspection'
    assert lift['grip_sha256'] == sha(paths[1].read_bytes())
    assert abs(lift['target']['Z'] - endpoint['Z'] - 5) < .01
    assert run['status'] == 'full_calibration_loaded_home_completed_pending_operator_assessment'
    for robot in (grip['after']['robot'], lift['final_state']['robot'], home['state']['robot']):
        assert not robot['errors'] and abs(robot['external_axes']['E1'] - 3.9) <= .15
    idle = dict(X=289.97, Y=62.63, Z=248.02, Rz=-3.88)
    assert all(abs(home['state']['robot']['pose_mm'][k]-v) < .05 for k,v in idle.items())
    assert profile['pickup_correction']['distance_mm'] == 10.4
    OUT.mkdir(exist_ok=False)
    (OUT/'profile_before_binding.json').write_bytes(PROFILE.read_bytes())
    confirmation = dict(at=time.time(), operator_feedback=FEEDBACK,
        scope='Operator confirms the existing +Y10.4 long-side geometry and requests binding of its successful grip evidence. No new physical trial or new retention observation was performed today by this script.')
    confirmation_path = OUT/'operator_confirmation.json'
    confirmation_path.write_text(json.dumps(confirmation,indent=2),encoding='utf-8')
    paths.append(confirmation_path)
    record = dict(schema='cephla.accepted-plate-grip.v1', at=time.time(),
        plate_profile_id=profile['id'],
        status='operator_accepted_supervised_closure_and_loaded_home_transfer',
        operator_feedback=FEEDBACK,
        acceptance_context='Retrospective operator approval to bind the previously successful unchanged +Y10.4 long-side pickup; historical pending-assessment receipts remain unchanged.',
        plate_retained_during_lift_and_home_operator_confirmed=True,
        new_physical_trial_performed=False, new_retention_observation_claimed=False,
        settings=dict(target_e1_mm=3.9,closing_speed=5,proof_lift_mm=5,proof_lift_speed=5),
        taught_endpoint=deepcopy(endpoint), source_profile_sha256=digest,
        force_control=False, force_limits_changed=False,
        validation_scope='Long-side pickup, 5 mm proof lift and historical loaded IDLE return only. Revised full-calibration reseat/open-28/rise-30 finish and holder rotation remain separately pending physical validation.',
        evidence=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p.read_bytes())) for p in paths])
    output = OUT/'accepted_grip_binding.json'
    output.write_text(json.dumps(record,indent=2),encoding='utf-8')
    profile.update(accepted_grip_reference=output.relative_to(ROOT).as_posix(),
        accepted_grip_reference_sha256=sha(output.read_bytes()),
        physical_grip_validated_for_plate=True,current_placement_grip_tested=True,
        gripping_edge_height='Accepted long-side gripping TCP Z73.718 mm at the unchanged HOME holder setup.',
        candidate_z_basis='Operator-accepted long-side descent/grip endpoint; successful recorded pickup and 5 mm lift.',
        alignment_name='48-well long-side alignment at HOME',
        alignment_frame='robot base Cartesian TCP, mm/degrees',
        alignment_scope='Original holder orientation near E2=1.77 degrees; +Y10.4 already included, never cumulative.',
        alignment_hover_pose_key='alignment_pose_mm',
        long_side_gripping_pose_key='candidate_endpoint')
    accepted_grip(profile)
    candidate = OUT/'profile_with_binding.json'
    candidate.write_text(json.dumps(profile,indent=2)+'\n',encoding='utf-8')
    load(candidate)
    assert sha(PROFILE.read_bytes()) == digest
    temporary = PROFILE.with_suffix('.binding.tmp')
    temporary.write_bytes(candidate.read_bytes())
    temporary.replace(PROFILE)
    from plate48_workflow import reference
    verified, new_sha, _ = reference()
    assert verified['candidate_endpoint'] == endpoint
    print(json.dumps(dict(grip_reference=str(output),profile_sha256=new_sha,
        long_side_alignment=verified['alignment_pose_mm'],gripping_endpoint=endpoint,
        grip_binding_ready=True,hardware_commands_sent=False)))


if __name__ == '__main__':
    main()
