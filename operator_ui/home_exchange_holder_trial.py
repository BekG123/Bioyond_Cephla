"""Fresh receipt-bound IDLE -> HOME seating trial; never releases implicitly.

Reuses the existing reverse holder-return planner and guarded executor.
Preparation is read-only with respect to hardware. Seating ends with the
3.9 mm grip unchanged, awaiting actual operator support inspection.
"""
import argparse
import json
import time
from pathlib import Path

import return_48well_holder as holder
from calibration_e2 import accepted
from draggo import DragGoRPC
from projected_pickup import ROOT, PROFILE, sha
from proof_lift_plate import api, near, write


def bind(run_path):
    run_path = Path(run_path).resolve()
    if ROOT / 'operator_ui/reports' not in run_path.parents:
        raise RuntimeError('Use a calibration report inside this repository.')
    raw = run_path.read_bytes()
    run = json.loads(raw)
    if run.get('status') != 'full_calibration_loaded_home_completed_pending_operator_assessment':
        raise RuntimeError('Successful calibration, proof lift and IDLE return required.')
    if sha(PROFILE.read_bytes()) != run['pickup_profile_sha256']:
        raise RuntimeError('Pickup geometry changed since this calibration.')
    folder = Path(run['calibration_folder']).resolve()
    if ROOT / 'operator_ui/reports/projected_alignment' not in folder.parents:
        raise RuntimeError('Unexpected pickup evidence directory.')
    proof_path = folder / 'proof_lift.json'
    proof = json.loads(proof_path.read_bytes())
    if (proof.get('status') != 'lift_completed_awaiting_visual_inspection'
            or proof.get('profile_sha256') != run['pickup_profile_sha256']
            or proof.get('grasp_verified') is not False):
        raise RuntimeError('Matching proof-lift receipt required; no invented observation.')
    near(proof['start'], json.loads(PROFILE.read_bytes())['candidate_endpoint'], .1)
    near(proof['final_state']['robot']['pose_mm'], dict(proof['start'], Z=proof['start']['Z']+5), .1)
    near(run['final_state']['robot']['pose_mm'], dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88), .1)
    holder.SOURCE = proof_path
    holder.PLAN = run_path.parent / 'home_holder_return_plan.json'
    holder.RECEIPT = run_path.parent / 'home_holder_seating_trial.json'
    return run, dict(calibration_report=run_path.relative_to(ROOT).as_posix(),
                     calibration_report_sha256=sha(raw),
                     pickup_profile_sha256=run['pickup_profile_sha256'])


def verify_holder_stationary():
    samples = []
    for _ in range(3):
        n = DragGoRPC('192.168.201.220').info()
        if (any(n.get(k, True) for k in ('moving','error','emergency','drag','manual'))
                or n.get('external_units', {}).get('E2') != 'degrees'
                or not accepted(n['external_axes']['E2'])):
            raise RuntimeError('Original holder orientation must be stationary and verified.')
        samples.append(dict(at=time.time(), native=n))
        time.sleep(.1)
    return samples


def prepare(run_path):
    run, binding = bind(run_path)
    state = api('state')
    near(state['robot']['pose_mm'], run['final_state']['robot']['pose_mm'], .1)
    samples = verify_holder_stationary()
    holder.prepare()
    plan = json.loads(holder.PLAN.read_bytes())
    plan.update(location_schema=2, origin='IDLE', destination='HOME',
                binding=binding, original_holder_samples=samples,
                authorization='Operator confirmed pickup/return route clear, hands clear and E-stop supervised; requested HOME seating trial. Stop before release for support inspection.',
                release_allowed=False, rotate_allowed=False,
                next_phase='Verify plate support before release, then lift 5 mm and open E1 to 28 mm.')
    write(holder.PLAN, plan)


def seat(run_path):
    _, binding = bind(run_path)
    plan = json.loads(holder.PLAN.read_bytes())
    if plan.get('binding') != binding:
        raise RuntimeError('Calibration evidence changed after return planning.')
    if not 0 <= time.time() - plan['at'] <= 600:
        raise RuntimeError('Holder-return plan expired; prepare a fresh reviewed trial.')
    verify_holder_stationary()
    holder.execute()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'seat'])
    parser.add_argument('calibration_report')
    parser.add_argument('--execute-confirmed', action='store_true')
    args = parser.parse_args()
    if args.phase == 'seat' and not args.execute_confirmed:
        parser.error('Seating requires explicit execution confirmation.')
    (prepare if args.phase == 'prepare' else seat)(args.calibration_report)
