"""Record the operator-accepted alignment and prepare an open-claw descent.

Reads live status, checks the existing IK/Lua plan, and updates the plate
profile. Never sends arm, claw, enable, reset, or sequence-start commands.
"""
import argparse,json,time
from copy import deepcopy
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch
import projected_pickup as pickup
from sequences import get_robot_params,band_floor
from autonomy import TransferError,ensure_arrival

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial-report',default='operator_ui/reports/projected_alignment/alignment_inward_trial_20261027.json')
    parser.add_argument('--supervised-outward-trial',action='store_true')
    args=parser.parse_args()
    root=pickup.ROOT
    trial_path=root/args.trial_report
    raw_trial=trial_path.read_bytes();trial=json.loads(raw_trial)
    if args.supervised_outward_trial:
        if (trial.get('direction')!='away_from_robot_base' or trial.get('distance_mm')!=2
                or trial.get('operator_authorized_open_claw_trial') is not True
                or trial.get('arrival_verified') is not True):
            raise TransferError('Explicit outward trial authorization and verified arrival required.')
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as response:s=json.load(response)
    r=s['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or s['sequence']['active']
            or not s['envelope']['enabled']):raise TransferError('Healthy idle controller and active workspace required.')
    pose=r['pose_mm'];accepted=trial['measured_pose']
    if any(abs(pose[k]-accepted[k])>.05 for k in ('X','Y','Z','Rz')):
        raise TransferError('Arm differs from the visually accepted corrected alignment.')
    pickup.evidence(trial['alignment_log'],trial['alignment_log_sha256'])
    old,digest=pickup.load()
    if abs(old['candidate_endpoint']['Z']-78.718)>.001:
        raise TransferError('Previous supervised descent height changed.')
    folder=root/'operator_ui/reports/projected_alignment'
    stamp=str(time.time_ns())
    backup=folder/('pickup_profile_before_corrected_alignment_'+stamp+'.json')
    backup.write_bytes(pickup.PROFILE.read_bytes())
    approval=dict(schema='cephla.projected-alignment-acceptance.v1',at=time.time(),
        visual_alignment_accepted=not args.supervised_outward_trial,alignment_pose_mm=accepted,
        supervised_open_claw_trial_authorized=args.supervised_outward_trial,
        operator_feedback=trial['operator_request'] if args.supervised_outward_trial else 'Looks centered now. Attempt descend.',
        corrected_alignment_evidence=trial_path.relative_to(root).as_posix(),
        corrected_alignment_sha256=pickup.sha(raw_trial),
        inward_correction_already_applied=not args.supervised_outward_trial,
        outward_correction_already_applied=args.supervised_outward_trial,
        descent_accepted=False,grip_verified=False)
    approval_path=folder/('corrected_alignment_accepted_'+stamp+'.json')
    approval_path.write_text(json.dumps(approval,indent=2),encoding='utf-8')
    candidate=deepcopy(old)
    for key in ('lateral_correction','lateral_correction_sha256','descent_acceptance','descent_acceptance_sha256'):
        candidate.pop(key,None)
    candidate.update(acceptance=approval_path.relative_to(root).as_posix(),
        acceptance_sha256=pickup.sha(approval_path.read_bytes()),
        alignment_log=trial['alignment_log'],alignment_log_sha256=trial['alignment_log_sha256'],
        alignment_pose_mm=accepted,candidate_endpoint=dict(accepted,Z=78.718),
        descent_status='pending_supervised_open_claw_trial',
        candidate_z_basis='Reuse previous supervised 48-well trial height Z78.718 at the corrected alignment for an open-claw trial; no automatic grip.',
        inward_correction_already_applied=not args.supervised_outward_trial,
        outward_correction_already_applied=args.supervised_outward_trial,
        previous_profile=backup.relative_to(root).as_posix(),
        previous_profile_sha256=digest)
    candidate_path=folder/('corrected_descent_candidate_'+stamp+'.json')
    candidate_path.write_text(json.dumps(candidate,indent=2),encoding='utf-8')
    verified,new_digest=pickup.load(candidate_path)
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    with patch.object(pickup,'load',return_value=(verified,new_digest)):
        target=pickup.target(trial=True)
        plan=pickup.descent_plan(pose,r['joints'],target,get_robot_params(),env,band_floor())
    if plan['legs']:raise TransferError('Unexpected lateral correction; shift is already applied.')
    report=dict(at=time.time(),profile_sha256=new_digest,plan=plan,
        claw_open_target_mm=28,fast_speed=137,slow_speed=5,slow_zone_start_z_mm=98.718,
        open_claw_trial=True,automatic_grip=False,automatic_lift=False,motion_started=False)
    output=folder/('corrected_descent_prepared_'+stamp+'.json')
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    temp=pickup.PROFILE.with_suffix('.tmp');temp.write_bytes(candidate_path.read_bytes());temp.replace(pickup.PROFILE)
    print(json.dumps(dict(report=str(output),profile_sha256=new_digest,endpoint=plan['endpoint'],
        lateral_moves=len(plan['legs']),motion_started=False)))

if __name__=='__main__':main()
