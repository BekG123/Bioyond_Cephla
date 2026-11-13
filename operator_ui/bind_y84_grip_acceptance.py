"""Bind the previously operator-accepted pickup trial; no hardware access."""
import json
import time
from projected_pickup import ROOT, PROFILE, load, sha, accepted_grip
from scope_step_trial import near


def main():
    profile, digest = load()
    folder = ROOT/'operator_ui/reports/projected_alignment/positive_y84_b9bdbc5a1efa4f7186e75235a7514d8e'
    paths = [folder/'grip_attempt.json', folder/'proof_lift.json',
             ROOT/'operator_ui/reports/ik_home/1793525450641843900_ae23d0a7cc8b4c8cb4364382a64a0e1d.json',
             ROOT/'operator_ui/reports/squid_48well_approach/loaded_trial_50e9db8eb2104d939a1c66ca1f75dab3.json']
    grip, lift, home, transfer = [json.loads(p.read_bytes()) for p in paths]
    assert grip['pose'] == profile['candidate_endpoint']
    assert grip['target_e1_mm'] == 3.9 and grip['speed'] == 5
    assert grip['status'] == 'closed_awaiting_operator_inspection'
    assert lift['status'] == 'lift_completed_awaiting_visual_inspection'
    assert lift['grip_sha256'] == sha(paths[0].read_bytes())
    assert home['status'] == 'completed' and home['sequence']['result']['ok'] is True
    near(home['plan']['start'], lift['target'], .1)
    assert transfer['status'] == 'loaded_seated_awaiting_human_release_confirmation'
    for robot in (grip['after']['robot'], lift['final_state']['robot'], transfer['final_robot']):
        assert not robot['errors'] and abs(robot['external_axes']['E1']-3.9) <= .07
    record = dict(schema='cephla.accepted-plate-grip.v1', at=time.time(), plate_profile_id=profile['id'],
        status='operator_accepted_supervised_closure_and_loaded_home_transfer',
        operator_feedback='It worked perfectly. Use the same drop off and home then to Squid + pickup back home pipeline. The one we tested and worked',
        acceptance_context='Confirmation after this pickup, loaded Home return and loaded Squid delivery; excludes later Squid retrievals reported tilted.',
        plate_retained_during_lift_and_home_operator_confirmed=True,
        settings=dict(target_e1_mm=3.9, closing_speed=5, proof_lift_mm=5, proof_lift_speed=5),
        taught_endpoint=profile['candidate_endpoint'], source_profile_sha256=digest,
        force_control=False, force_limits_changed=False, uninterrupted_full_pipeline=False,
        evidence=[dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p.read_bytes())) for p in paths])
    output = folder/'accepted_grip_binding.json'
    backup = folder/'profile_before_grip_binding.json'
    with backup.open('x', encoding='utf-8') as f:
        f.write(PROFILE.read_text(encoding='utf-8'))
    with output.open('x', encoding='utf-8') as f:
        json.dump(record,f,indent=2)
    profile.update(accepted_grip_reference=output.relative_to(ROOT).as_posix(),
                   accepted_grip_reference_sha256=sha(output.read_bytes()),
                   physical_grip_validated_for_plate=True, current_placement_grip_tested=True)
    accepted_grip(profile)
    candidate = folder/'profile_with_grip_binding.json'
    candidate.write_text(json.dumps(profile,indent=2),encoding='utf-8')
    load(candidate)
    assert sha(PROFILE.read_bytes()) == digest
    temp = PROFILE.with_suffix('.tmp')
    temp.write_bytes(candidate.read_bytes())
    temp.replace(PROFILE)
    print(json.dumps(dict(saved=str(output),profile_sha256=sha(PROFILE.read_bytes()),hardware_commands_sent=False)))


if __name__ == '__main__':
    main()
