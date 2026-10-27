"""Save operator-accepted 48-well grip evidence; no hardware commands."""
import json
import time
from projected_pickup import ROOT, load, sha


def main():
    profile,digest=load()
    folder=ROOT/'operator_ui/reports/projected_alignment'
    names=['regrip_3p9_reseated_20261027.json','proof_lift_3p9_5mm_20261027.json',
           'reseated_48well_home_completion_20261027.json']
    records=[json.loads((folder/n).read_bytes()) for n in names]
    grip,lift,home=records
    if (grip['target_e1_mm']!=3.9 or not home['home_sequence']['result']['ok']
            or home['grip_setting_mm']!=3.9 or not home['proof_lift_operator_confirmed']):
        raise RuntimeError('Successful 3.9 mm grip/lift/Home evidence required.')
    path=ROOT/'Pick and Hold/Grip/accepted_48well_grip_reference.json'
    if path.exists():
        raise RuntimeError('Acceptance already recorded; do not overwrite historical evidence.')
    record=dict(schema='cephla.accepted-plate-grip.v1',at=time.time(),plate_profile_id=profile['id'],
        status='operator_accepted_supervised_closure_and_loaded_home_transfer',
        operator_feedback='Awesome job. This worked excellently. Lets save the current grip as the one thats good for the 48 plate.',
        plate_retained_during_lift_and_home_operator_confirmed=True,
        settings=dict(target_e1_mm=3.9,closing_speed=5,proof_lift_mm=5,proof_lift_speed=5,
                      home_translation_speed=137,wrist_speed=30),
        taught_endpoint=profile['candidate_endpoint'],source_profile_sha256=digest,
        measured_grip_pose=grip['after']['robot']['pose_mm'],
        home_e1_mm=home['final_state']['robot']['external_axes']['E1'],
        stationary_grip_feedback=grip['steps'][-1] if 'steps' in grip else None,
        force_control=False,force_limits_changed=False,
        uninterrupted_full_pipeline=False,
        note='Accepted position-based grip, not calibrated grip force. Prior stopped attempt and empty restart remain in history.',
        evidence=[dict(path=(folder/n).relative_to(ROOT).as_posix(),sha256=sha((folder/n).read_bytes())) for n in names])
    with path.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    print(json.dumps(dict(saved=str(path),target_e1_mm=3.9,hardware_commands_sent=False)))


if __name__=='__main__':main()
