"""Offline route preparation, then explicitly authorized calibration and transfer."""
import json
import sys
from copy import deepcopy
from capture_squid_approach_20261103 import FOLDER, sha, save
from prepare_squid_destination import validate
from proof_lift_plate import api
import full_calibration_handling_20261103 as calibration
import execute_continuous_squid_return_20261103 as travel

CAPTURE = FOLDER / 'taught_relocated_squid_20261108T071447205563Z.json'
PARENT = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
PLAN = FOLDER / 'relocated_squid_candidate_20261107.json'
OUT = FOLDER / 'calibration_new_squid_trial_20261107'
AUTH = ('Operator moved microscope, taught the new seated destination, returned '
        'plate to pickup holder and arm near Home, and requested full calibration '
        'then transfer to this destination. Keep claws closed; no release or return.')

def prepare():
    assert sha(PARENT) == '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81'
    taught = json.loads(CAPTURE.read_bytes())
    evidence = __import__('pathlib').Path(taught['home_evidence'])
    assert sha(evidence) == taught['home_evidence_sha256']
    home = json.loads(evidence.read_bytes())['state']['robot']
    plan = deepcopy(json.loads(PARENT.read_bytes()))
    route = plan['routes']['from_capture'][:5]
    route[0] = {k: home['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    route[3] = dict(taught['target'], Z=291.24)
    route[4] = dict(taught['target'])
    assert route[4]['Z'] + 5 < route[3]['Z']
    forward = validate(route, home['joints'], plan['cfg'], plan['envelope'])
    delta = {k: forward['final_joints'][k]-v for k,v in taught['source_state']['robot']['joints'].items()}
    if any(abs(v) > .5 for v in delta.values()):
        raise RuntimeError('Taught joint configuration mismatch')
    quantized = [{k: round(v,2) for k,v in p.items()} for p in route]
    validate(quantized, home['joints'], plan['cfg'], plan['envelope'])
    reverse = validate(list(reversed(route)), taught['source_state']['robot']['joints'], plan['cfg'], plan['envelope'])
    plan.update(routes=dict(from_capture=route), leg_speeds=[137,137,137,5],
                operator_intent=AUTH, capture=str(CAPTURE), capture_sha256=sha(CAPTURE),
                home_evidence=str(evidence), home_evidence_sha256=sha(evidence),
                validation=dict(forward=forward, reverse=reverse, taught_joint_difference=delta),
                completion_status='new_squid_destination_reached_pending_operator_assessment',
                status='offline_validated_pending_physical_trial', release_authorized=False,
                collision_clearance_verified=False)
    if PLAN.exists():
        if json.loads(PLAN.read_bytes()) != plan:
            raise RuntimeError('Candidate already exists with different content')
    else:
        save(PLAN, plan)
    print(json.dumps(dict(plan=str(PLAN),sha256=sha(PLAN),route=route,joint_difference=delta)), flush=True)

if __name__ == '__main__':
    prepare()
    if '--execute' in sys.argv:
        calibration.OUT = OUT
        calibration.AUTH = AUTH
        calibration.main(calibration_only=True)
        result = json.loads((OUT/'run.json').read_bytes())
        if result['status'] != 'full_calibration_loaded_home_completed_pending_operator_assessment':
            raise RuntimeError('Fresh calibration did not complete')
        travel.PLAN, travel.SHA = PLAN, sha(PLAN)
        travel.OUTPUT = OUT/'new_destination_transfer.json'
        travel.main(expected_speeds=(137,137,137,5), vertical_legs=(0,3))
