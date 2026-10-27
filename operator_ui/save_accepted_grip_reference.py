"""Build an offline evidence reference; no controller access or runtime activation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
TRIALS = ROOT/'operator_ui/demonstrations/supervised_grip'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def source(path):
    return dict(path=path.relative_to(ROOT).as_posix(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def main():
    step_path = TRIALS/'5b78a0334fc34f2885208bc453e3a7bf.json'
    home_path = TRIALS/'contact_3p8_lacry_home_trial.json'
    actual_home = ROOT/'operator_ui/reports/ik_home/1792484685745825600_5245de30b33e4c25b5dc686c6320ddeb.json'
    descent_path = ROOT/'Pick and Hold/Descend/corrected_endpoint.json'
    step, home, runtime, descent = map(read, (step_path, home_path, actual_home, descent_path))
    assert step['status'] == 'stopped_awaiting_operator_review'
    assert step['target_mm'] == 3.8 and step['speed'] == 5
    assert all(s['ok'] and s['telemetry_live'] for s in step['samples'])
    assert home['accepted_loaded_home_transfer'] is True
    assert runtime['status'] == 'completed' and runtime['sequence']['result']['ok'] is True
    paths = [
        TRIALS/'cdcc8e1f0c774b5ab0fe3cafed7b4ffe.json', step_path,
        TRIALS/'5b78a0334fc34f2885208bc453e3a7bf_review.json',
        TRIALS/'contact_3p8_first_lift_acceptance.json',
        TRIALS/'contact_3p8_proof_lift_plan_proof_lift.json',
        TRIALS/'contact_3p8_second_lift_plan_proof_lift.json',
        home_path, actual_home, descent_path]
    for path in paths[4:6]:
        assert read(path)['status'] == 'lift_completed_awaiting_visual_inspection'
    torque = [s['e1_torque'] for s in step['samples']]
    pose = step['after']['robot']['pose_mm']
    delta = {k: pose[k]-descent['endpoint'][k] for k in ('X','Y','Z','Rz')}
    reference = dict(
        schema='cephla.accepted-grip-reference.v1',
        id='two_disk_plate_e1_3p8_accepted_20261020',
        created_utc=datetime.now(timezone.utc).isoformat(),
        purpose='Evidence reference for the final Grip stage after Calibrate -> Align -> Descend.',
        status='operator_accepted_supervised_closure_and_loaded_home_transfer',
        settings=dict(control='E1 position increments', target_e1_mm=3.8,
                      closing_speed=5, increment_mm=.1,
                      evidenced_final_steps_mm=[4.0, 3.9, 3.8],
                      controller_mode='auto', preserve_other_axes=True,
                      startup_with_plate_allowed=False),
        closure=dict(pose_mm_degrees=pose,
                     joints=step['after']['robot']['joints'],
                     settled_e1_mm=step['after']['robot']['external_axes']['E1'],
                     stationary_reports=step['samples'],
                     raw_e1_torque=dict(samples=torque, mean=mean(torque),
                                        minimum=min(torque), maximum=max(torque),
                                        units='controller-reported, physical force/torque units unestablished'),
                     immediate_completion=step['command_result']['gripper'],
                     controller_grip_detected=step['command_result']['gripper']['grip_detected'],
                     acceptance_basis='Operator confirmed even contact without gap, level proof lift and successful loaded Home transfer.'),
        validation=dict(proof_lifts_mm=[5,5], total_lift_mm=10, lift_speed=5,
                        loaded_home_algorithm='Lacry IKHomeConnection -> ResearcherHome -> Lua queue',
                        translation_speed=137, wrist_speed=30,
                        home_pose_mm_degrees=home['final_pose_mm'],
                        home_e1_mm=home['final_e1_mm'], controller_errors=[],
                        operator_outcome=home['operator_outcome']),
        interpretation=dict(torque_is_observation_not_setpoint=True,
                            force_limits=None, force_units=None,
                            contact_torque_threshold=None, closing_torque_sign=None,
                            matched_empty_baseline_at_this_pose=False,
                            transferable_force_model_validated=False),
        integration=dict(runtime_activated=False,
                         installed_grip='pick_and_hold.Grip.torque.TorqueGrip',
                         installed_vendor_profile_still_unreviewed=True,
                         descent_profile=source(descent_path),
                         successful_pose_minus_saved_descent=delta,
                         same_as_saved_descent_endpoint=False,
                         responsibilities='Descend owns arm positioning. Grip owns E1 closure only.',
                         next_review='Reconcile the accepted grip pose with the descent profile and validate the staged Grip implementation. Do not add the delta to arbitrary future placements.',
                         initial_closure_from_28mm_at_successful_pose_validated=False),
        evidence=[source(path) for path in paths])
    output = ROOT/'Pick and Hold/Grip/accepted_grip_reference.json'
    if output.exists():
        raise RuntimeError('Reference already exists; preserve it and review before replacement.')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(reference, stream, indent=2, allow_nan=False)
        stream.write('\n')
    saved = read(output)
    assert saved == reference
    for item in saved['evidence']:
        assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest() == item['sha256']
    print(json.dumps(dict(saved=str(output), target_e1_mm=3.8, speed=5,
                          mean_raw_torque=mean(torque), source_records_verified=len(paths),
                          descent_delta=delta, runtime_activated=False), indent=2))


if __name__ == '__main__':
    main()
