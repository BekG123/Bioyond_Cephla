"""Prepare the operator-requested 2 mm correction and return route; no motion."""
from copy import deepcopy
import json
from urllib.request import urlopen
from projected_pickup import ROOT,PROFILE,load,sha,inward_endpoint
from autonomy import alignment_plan,TransferError
from pick_and_hold.Descend.lua_executor import make_plan
from sequences import band_floor

def main():
    p,digest=load()
    if p.get('lateral_correction'):raise TransferError('A correction is already configured; do not add it twice.')
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as response:s=json.load(response)
    r=s['robot']
    if s['sequence']['active'] or not r.get('connected') or not r.get('ok') or r.get('errors'):
        raise TransferError('Healthy stationary feedback required.')
    cfg_path=ROOT/'operator_ui/robot_params.json';cfg=json.loads(cfg_path.read_bytes())
    source=p['candidate_endpoint'];goal=inward_endpoint(source,cfg)
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    t=dict(x=goal['X'],y=goal['Y'],rz=goal['Rz'],z_calibrated=goal['Z'])
    route=alignment_plan(r['pose_mm'],t,r['joints'],cfg,env,300.,validate_descent=True)
    folder=ROOT/'operator_ui/reports/projected_alignment'
    evidence=dict(direction='toward_robot_base',distance_mm=2,operator_direction_confirmed=True,
        operator_moved_away_after_inspection=True,source_endpoint=source,candidate_endpoint=goal,
        parent_profile_sha256=digest,robot_params=cfg_path.relative_to(ROOT).as_posix(),
        robot_params_sha256=sha(cfg_path.read_bytes()),hardware_validated=False,
        note='Apply once relative to trial endpoint, not the raised inspection pose; preserve Z/yaw.')
    ep=folder/'inward_2mm_correction_20261026.json';ep.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    candidate=deepcopy(p)
    candidate.update(candidate_endpoint=goal,lateral_correction=ep.relative_to(ROOT).as_posix(),
        lateral_correction_sha256=sha(ep.read_bytes()),descent_status='pending_supervised_open_claw_trial')
    cp=folder/'inward_2mm_candidate_profile_20261026.json';cp.write_text(json.dumps(candidate,indent=2),encoding='utf-8')
    load(cp)
    review=dict(motion_started=False,profile_activated=False,source_profile_sha256=digest,
        candidate_profile=cp.relative_to(ROOT).as_posix(),candidate_profile_sha256=sha(cp.read_bytes()),
        before=s,alignment_waypoints=route,endpoint=goal,alignment_translation_speed=5,
        alignment_wrist_speed=30,claw_open_mm=28,descent_speeds=[137,5],
        slow_zone_start_z=goal['Z']+20,grip_requested=False)
    rp=folder/'inward_2mm_review_20261026.json';rp.write_text(json.dumps(review,indent=2),encoding='utf-8')
    print(json.dumps(dict(review=str(rp),start=r['pose_mm'],candidate_endpoint=goal,
        delta_xy=[goal[k]-source[k] for k in ('X','Y')],waypoints=len(route),motion_started=False)))

if __name__=='__main__':main()
