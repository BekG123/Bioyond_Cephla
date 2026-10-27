"""Prepare/activate the requested long-edge 10 mm and down 5 mm open-claw trial.

Never moves hardware. Activation requires actual arrival at the checked hover.
The old successful profile/evidence is retained, and new Grip remains blocked.
"""
import argparse,json,math,time
from copy import deepcopy
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch
import projected_pickup as p
from autonomy import check_path,ensure_arrival,wrap,TransferError
from sequences import get_robot_params,band_floor

FOLDER=p.ROOT/'operator_ui/reports/projected_alignment'
PLAN=FOLDER/'forward_lower_trial_plan_20261027.json'
SOURCE='f3932615fca0640033099d35726290317cfee7f8e1658ff3aaed42ff01f13075'

def api(path):
    with urlopen('http://127.0.0.1:5002/'+path,timeout=8) as response:return json.load(response)

def save(path,data):
    if path.exists():raise TransferError('Do not overwrite existing trial evidence.')
    path.write_text(json.dumps(data,indent=2),encoding='utf-8')
    return path.relative_to(p.ROOT).as_posix(),p.sha(path.read_bytes())

def main():
    raise TransferError('This camera-derived forward correction was rejected by the operator. Use the restored centering reference and verify the physical long-axis direction before a new trial.')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--activate',action='store_true')
    args=parser.parse_args();s=api('state');r=s['robot'];old,digest=p.load()
    if digest!=SOURCE:raise TransferError('Source plate profile changed; no cumulative correction.')
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or s['sequence']['active']
            or not s['envelope']['enabled'] or r['program_state']['state']!='running'):
        raise TransferError('Healthy idle running controller required.')
    cfg=get_robot_params();env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    if args.activate:
        review=json.loads(PLAN.read_bytes())
        if review['source_profile_sha256']!=digest:raise TransferError('Source evidence changed.')
        ensure_arrival(r['pose_mm'],review['hover'])
        candidate=Path(p.evidence(review['candidate_profile'],review['candidate_profile_sha256']))
        profile,new_digest=p.load(candidate)
        with patch.object(p,'load',return_value=(profile,new_digest)):
            plan=p.descent_plan(r['pose_mm'],r['joints'],p.target(trial=True),cfg,env,band_floor())
        save(FOLDER/'forward_lower_hover_arrival_20261027.json',dict(at=time.time(),robot=r,plan=plan))
        temp=p.PROFILE.with_suffix('.tmp');temp.write_bytes(candidate.read_bytes());temp.replace(p.PROFILE)
        print(json.dumps(dict(activated=True,profile_sha256=new_digest,endpoint=profile['candidate_endpoint'])))
        return
    q=api('seq')
    if q['name']!='projected_alignment' or q['state']!='done' or not q['result']['ok']:
        raise TransferError('Fresh successful projected alignment required.')
    prior=json.loads((FOLDER/'alignment_outward_trial_20261027.json').read_bytes())['source_alignment_pose']
    target=q['result']['route']['target'];start=r['pose_mm']
    ensure_arrival(start,dict(X=target['x'],Y=target['y'],Z=300.,Rz=target['rz']))
    difference=math.hypot(start['X']-prior['X'],start['Y']-prior['Y'])
    if difference>.5 or abs(wrap(start['Rz']-prior['Rz']))>.2:
        raise TransferError('Plate alignment changed beyond the reviewed placement; review before correction.')
    proposal_path=FOLDER/'48well_slip_position_correction_pending_20261027.json'
    proposal=json.loads(proposal_path.read_bytes());goal=proposal['candidate_endpoint_mm']
    original=old['candidate_endpoint']
    if (abs(math.hypot(goal['X']-original['X'],goal['Y']-original['Y'])-10)>.005
            or abs(goal['Z']-original['Z']+5)>.001 or goal['Rz']!=original['Rz']):
        raise TransferError('Correction differs from requested 10 mm forward/down 5 mm.')
    hover=dict(goal,Z=300.);joints=check_path(start,hover,r['joints'],cfg,env)
    backup,backup_sha=save(FOLDER/'profile_before_forward_lower_20261027.json',old)
    log=Path(q['result']['log_file'])
    approval,approval_sha=save(FOLDER/'forward_lower_trial_authorization_20261027.json',dict(
        visual_alignment_accepted=False,supervised_open_claw_trial_authorized=True,alignment_pose_mm=hover,
        operator_request='10 mm parallel to plate long side away from robot, and 5 mm lower; repeat after fault cleared, empty gripper, plate flat in same holder, hands clear and E-stop supervised.',
        proposal=proposal_path.relative_to(p.ROOT).as_posix(),proposal_sha256=p.sha(proposal_path.read_bytes()),
        descent_accepted=False,grip_verified=False))
    candidate=deepcopy(old)
    for key in ('descent_acceptance','descent_acceptance_sha256','lateral_correction','lateral_correction_sha256'):
        candidate.pop(key,None)
    candidate.update(acceptance=approval,acceptance_sha256=approval_sha,
        alignment_log=log.relative_to(p.ROOT).as_posix(),alignment_log_sha256=p.sha(log.read_bytes()),
        alignment_pose_mm=hover,candidate_endpoint=goal,descent_status='pending_supervised_open_claw_trial',
        candidate_z_basis='Operator-requested 5 mm below prior accepted Z78.718; new Z73.718 awaits open-claw trial.',
        previous_profile=backup,previous_profile_sha256=backup_sha,
        forward_along_plate_long_edge_mm=10,additional_down_mm=5,
        physical_grip_validated_for_plate=False,automatic_lift_enabled=False,full_pickup_verified=False)
    path,candidate_sha=save(FOLDER/'forward_lower_candidate_profile_20261027.json',candidate)
    verified,new_digest=p.load(p.ROOT/path)
    with patch.object(p,'load',return_value=(verified,new_digest)):
        descent=p.descent_plan(hover,joints,p.target(trial=True),cfg,env,band_floor())
    save(PLAN,dict(at=time.time(),source_profile_sha256=digest,start=start,hover=hover,endpoint=goal,
        fresh_alignment_difference_mm=difference,alignment_result=q['result'],
        candidate_profile=path,candidate_profile_sha256=candidate_sha,
        correction_speed=5,descent=descent,approach_speed=137,final20mm_speed=5,
        open_before_descent_mm=28,automatic_grip=False,motion_started=False))
    print(json.dumps(dict(plan=str(PLAN),hover=hover,endpoint=goal,fresh_alignment_difference_mm=difference)))

if __name__=='__main__':main()
