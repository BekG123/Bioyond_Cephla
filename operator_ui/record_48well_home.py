"""Archive completed 48-well Home return. Read-only hardware access."""
import json
import argparse
import time
from proof_lift_plate import api,near
from projected_pickup import ROOT,sha,load


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accepted-repeat',type=int,choices=[1,2,3])
    parser.add_argument('--accepted-trial',choices=['squid_retry_20261027T1136','squid_nearby_20261027T1200','squid_reteach_e2_20261027','squid_clearance_20261027','squid_clearance_retry_20261027','squid_obstruction_removed_20261027','squid_full7_20261027']);args=parser.parse_args()
    if args.accepted_repeat and args.accepted_trial:raise RuntimeError('Select one trial receipt.')
    state=api('state');seq=api('seq');profile,digest=load()
    if (not state['robot'].get('connected') or state['robot'].get('errors') or seq['active']
            or seq['name']!='researcher_home' or not seq.get('result',{}).get('ok')):
        raise RuntimeError('Confirmed completed Home return required.')
    home=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
    near(state['robot']['pose_mm'],home,.1)
    folder=ROOT/'operator_ui/reports/projected_alignment'
    names=['even_spacing_reseated_full_trial_20261027.json',
           'regrip_3p9_reseated_20261027.json','proof_lift_3p9_5mm_20261027.json']
    if args.accepted_repeat:
        names=[f'repeat_{args.accepted_repeat}_grip_3p9_20261027.json',
               f'repeat_{args.accepted_repeat}_proof_lift_20261027.json']
    if args.accepted_trial:
        names=[f'{args.accepted_trial}_grip.json',f'{args.accepted_trial}_lift.json']
        grip=json.loads((folder/names[0]).read_bytes())
        lift=json.loads((folder/names[1]).read_bytes())
        if (grip.get('trial')!=args.accepted_trial or grip['profile_sha256']!=digest
                or lift.get('trial')!=args.accepted_trial or lift['profile_sha256']!=digest
                or lift['status']!='lift_completed_awaiting_visual_inspection'):
            raise RuntimeError('Matching completed grip/lift receipts required.')
    refs=[dict(path=(folder/name).relative_to(ROOT).as_posix(),sha256=sha((folder/name).read_bytes())) for name in names]
    record=dict(at=time.time(),status='home_motion_completed_awaiting_final_plate_inspection',
        evidence=refs,profile=profile,profile_sha256=digest,final_state=state,home_sequence=seq,
        proof_lift_operator_confirmed=True,proof_lift_feedback='Lift worked. No slipping.',
        user_requested_home=True,home_translation_speed=137,wrist_speed=30,
        grip_setting_mm=3.9,home_plate_retention_operator_confirmed=False,
        uninterrupted_full_pipeline=False,
        note='Successful 3.9 regrip followed empty restart; prior 3.8 settling failure retained separately. Do not label as one uninterrupted full-calibration run.')
    path=folder/'reseated_48well_home_completion_20261027.json'
    if args.accepted_repeat:
        path=folder/f'repeat_{args.accepted_repeat}_home_completion_20261027.json'
        record.update(repeat_number=args.accepted_repeat,proof_lift_operator_confirmed=False,
            proof_lift_feedback=None,uninterrupted_full_pipeline=False,
            note='Authorized repeat: grip, proof lift and Home motion completed. Operator retention confirmation pending; cycle1 included a visually inspected adapted descent.')
    if args.accepted_trial:
        path=folder/f'{args.accepted_trial}_home.json'
        record.update(trial=args.accepted_trial,proof_lift_operator_confirmed=False,
            proof_lift_feedback=None,uninterrupted_full_pipeline=True,
            note='Authorized retry used exact successful repeat-1 reference. Alignment, descent, grip, slow lift and Home completed without interruption; current plate retention awaits operator observation.')
        if args.accepted_trial=='squid_full7_20261027':
            record.update(uninterrupted_full_pipeline=False,
                note='Camera-adjusted placement inspected and accepted before grip; operator confirmed even contact and authorized slow lift, Home and Squid drop-off. Motion completed without faults; loaded retention awaits observation.')
    with path.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    print(json.dumps(dict(report=str(path),home=state['robot']['pose_mm'],e1=state['robot']['external_axes']['E1'])))


if __name__=='__main__':main()
