"""Save operator-accepted short-side grip settings without moving hardware."""
import hashlib
import json
from pathlib import Path
import time
from short_side_alignment_trial import FOLDER,reference_for_candidate

root=Path(__file__).resolve().parents[1]
plan,taught=reference_for_candidate('corrected02')
trial=FOLDER/'retry_grip25_and_proof_lift.json'
raw=trial.read_bytes();r=json.loads(raw)
assert r['status']=='lift_completed_awaiting_retention_inspection'
assert not r['final_state']['robot']['errors']
assert abs(r['final_state']['robot']['external_axes']['E1']-25)<.07
accept=FOLDER/'accepted_short_side25.json'
profile=root/'Pick and Hold/Grip/short_side_48well_reference.json'
if accept.exists() or profile.exists():raise RuntimeError('Acceptance exists; preserve original evidence')
settings=dict(profile_id='48well_short_side_corrected02_e1_25',
    alignment=taught['target'],descent_endpoint=r['low'],holder_e2_degrees=taught['e2_degrees'],
    approach_speed=137,descent_drop_mm=30,descent_speed=137,open_e1_mm=28,
    target_e1_mm=25,closing_speed=5,closing_targets_mm=[27,26,25.8,25.6,25.4,25.2,25],
    proof_lift_mm=5,proof_lift_speed=5,proof_lift_endpoint=r['high'])
evidence=[dict(path=str(p.relative_to(root)).replace('\\','/'),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    for p in (trial,FOLDER/'trial_corrected02.json',FOLDER/'grip_corrected02_28_to_26_trial.json',FOLDER/'proof_lift_corrected02_e1_26_operator_assessment.json')]
accepted=dict(status='operator_accepted_short_side_pickup_and_5mm_lift',at=time.time(),
    operator_feedback='Yes, it worked. Lets use this from now on.',physical_pickup_success=True,
    plate_level_and_secure_operator_confirmed=True,settings=settings,evidence=evidence,
    force_control=False,force_limits_changed=False,hamilton_transfer_validated=False,
    scope='This corrected 48-well short-side setup; long-side 3.9 mm reference remains separate.')
with accept.open('x') as f:json.dump(accepted,f,indent=2)
with profile.open('x') as f:json.dump(dict(accepted,
    acceptance_path=str(accept.relative_to(root)).replace('\\','/'),
    acceptance_sha256=hashlib.sha256(accept.read_bytes()).hexdigest()),f,indent=2)
print(json.dumps(dict(profile=str(profile),settings=settings,physical_pickup_success=True),indent=2))
