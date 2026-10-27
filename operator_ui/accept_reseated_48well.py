"""Record visual acceptance and bind the existing 3.9 grip to this placement.

No hardware commands; historical grip/lift evidence remains unchanged.
"""
from copy import deepcopy
import json
import time
from projected_pickup import ROOT,PROFILE,load,sha,evidence,accepted_grip
from proof_lift_plate import api,near
from correct_48well_centering import save


def main():
    profile,digest=load();state=api('state');seq=api('seq');robot=state['robot']
    result=seq.get('result') or {}
    if (not robot.get('connected') or not robot.get('ok') or robot.get('errors') or seq['active']
            or seq['name']!='researcher_descend' or seq['state']!='done' or not result.get('ok')
            or not result.get('open_claw_trial')
            or result.get('descent_correction',{}).get('profile_sha256')!=digest):
        raise RuntimeError('Fresh completed matching open-claw trial required.')
    near(robot['pose_mm'],profile['candidate_endpoint'],.1)
    if not 27.98<=robot['external_axes']['E1']<=28.05:raise RuntimeError('Jaws must remain open.')
    previous=json.loads(evidence(profile['previous_profile'],profile['previous_profile_sha256']).read_bytes())
    reference=accepted_grip(previous)
    if not reference:raise RuntimeError('Original accepted 3.9 grip evidence required.')
    approval,approval_sha=save('reseated_repeat1_visual_acceptance_20261027.json',dict(
        at=time.time(),visually_accepted=True,endpoint=profile['candidate_endpoint'],
        source_profile_sha256=digest,result=result,run_id=seq.get('run_id'),
        operator_feedback='Yes, jaws evenly spaced and correct gripping height. Continue',
        measured_state=state,source_sequence=seq,grip_target_e1_mm=3.9,
        current_placement_grip_tested=False,current_placement_lift_tested=False))
    # The retention flag refers to the original validated plate/grip setting,
    # not to a new lift. Preserve the original measured grip pose and evidence.
    bound=deepcopy(reference)
    bound.update(taught_endpoint=profile['candidate_endpoint'],
        original_taught_endpoint=reference['taught_endpoint'],
        source_grip_reference=previous['accepted_grip_reference'],
        source_grip_reference_sha256=previous['accepted_grip_reference_sha256'],
        placement_acceptance=approval,placement_acceptance_sha256=approval_sha,
        current_placement_grip_tested=False,current_placement_lift_tested=False,
        validation_scope='Original 3.9 mm grip and loaded Home success retained as historical evidence. Current adjusted jaw placement visually accepted; its new grip/lift is not yet tested.')
    bound['evidence']+= [dict(path=previous['accepted_grip_reference'],sha256=previous['accepted_grip_reference_sha256']),
                         dict(path=approval,sha256=approval_sha)]
    grip_path,grip_sha=save('reseated_repeat1_grip_binding_20261027.json',bound)
    profile.update(descent_status='operator_accepted_open_claw_descent',
        descent_acceptance=approval,descent_acceptance_sha256=approval_sha,
        accepted_grip_reference=grip_path,accepted_grip_reference_sha256=grip_sha,
        physical_grip_validated_for_plate=True,current_placement_grip_tested=False,
        full_pickup_verified=False,automatic_lift_enabled=False)
    path,new_sha=save('reseated_repeat1_accepted_profile_20261027.json',profile)
    accepted,_=load(ROOT/path);accepted_grip(accepted)
    temp=PROFILE.with_suffix('.tmp');temp.write_bytes((ROOT/path).read_bytes());temp.replace(PROFILE)
    print(json.dumps(dict(profile_sha256=new_sha,grip_target_e1_mm=3.9,
        endpoint=profile['candidate_endpoint'],hardware_commands_sent=False)))


if __name__=='__main__':main()
