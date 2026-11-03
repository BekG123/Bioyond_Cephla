"""Bind this calibration's Home completion to one closed-claw Squid transfer."""
import argparse
import json
import time
from copy import deepcopy
import execute_continuous_squid_return_20261103 as runner
from capture_squid_approach_20261103 import FOLDER, sha, save
from proof_lift_plate import api, near, write
from projected_pickup import ROOT

CAL = ROOT / 'operator_ui/reports/projected_alignment/accepted_y104_repeat_81470b98b2f845208e3a628354e3afc4'
OUT = FOLDER / 'full_calibration_closed_transfer_20261103'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    source = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
    if sha(source) != '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81':
        raise RuntimeError('Accepted route changed')
    grip = json.loads((CAL / 'grip_attempt.json').read_bytes())
    proof = json.loads((CAL / 'proof_lift.json').read_bytes())
    home = json.loads((CAL / 'home_preview.json').read_bytes())['plan']
    if grip['status'] != 'closed_awaiting_operator_inspection' or proof['status'] != 'lift_completed_awaiting_visual_inspection' or not home['preserve_gripper']:
        raise RuntimeError('Successful pickup/lift and loaded Home required')
    if proof['grip_sha256'] != sha(CAL / 'grip_attempt.json'):
        raise RuntimeError('Proof lift belongs to another grip')
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip': '192.168.201.220'})
    state = api('state')
    seq = api('seq')
    if seq['active'] or seq['name'] != 'researcher_home' or not (seq.get('result') or {}).get('ok'):
        raise RuntimeError('Home completion unverified')
    near(state['robot']['pose_mm'], home['home'], .05)
    if abs(state['robot']['external_axes']['E1'] - 3.9) > .15:
        raise RuntimeError('Grip changed after pickup')
    OUT.mkdir(exist_ok=True)
    plan = deepcopy(json.loads(source.read_bytes()))
    plan['routes']['from_capture'] = plan['routes']['from_capture'][:5]
    plan['leg_speeds'] = [137, 137, 137, 5]
    plan['completion_status'] = 'calibrated_closed_transfer_completed_pending_operator_assessment'
    plan['operator_intent'] = 'Operator requested full calibration followed by closed-claw transfer; stop at Squid without release.'
    runner.PLAN = OUT / 'plan.json'
    runner.OUTPUT = OUT / 'trial.json'
    if runner.PLAN.exists():
        if json.loads(runner.PLAN.read_bytes()) != plan:
            raise RuntimeError('Trial plan changed')
    else:
        save(runner.PLAN, plan)
    runner.SHA = sha(runner.PLAN)
    if args.execute:
        save(OUT / 'calibration_completion.json', dict(status='calibration_alignment_descent_grip_proof_lift_loaded_home_completed',
             at=time.time(), calibration_folder=str(CAL), final_state=state, home_sequence=seq,
             evidence={name: sha(CAL / name) for name in ('attempt.json', 'grip_attempt.json', 'proof_lift.json', 'home_preview.json', 'home_dispatch.json')},
             new_visual_observation_claimed=False,
             pre_grip_connection_refusal='Idle disconnected before jaw dispatch; no grip receipt created; reconnected through Flask before executing grip.'))
    runner.main(expected_speeds=(137, 137, 137, 5), vertical_legs=(0, 3))


if __name__ == '__main__':
    main()
