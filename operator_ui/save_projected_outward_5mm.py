"""Save the measured additional 5 mm outward correction. No motion commands.

Pins the source profile to prevent cumulative reapplication. Plans the future
vertical descent offline; does not claim that new vertical path was replayed.
"""
import json,math,time
from copy import deepcopy
from urllib.request import urlopen
from unittest.mock import patch
import projected_pickup as pickup
from autonomy import check_path,TransferError
from sequences import get_robot_params,band_floor

SOURCE='e62d9dd25cad8624aae7180353743ebfece0137f958df4b174e267a49359e5d2'

def main():
    old,digest=pickup.load()
    if digest!=SOURCE:raise TransferError('Source profile changed; do not apply correction twice.')
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as r:s=json.load(r)
    r=s['robot'];cfg=get_robot_params()
    if (not r.get('connected') or not r.get('ok') or r.get('errors')
            or s['sequence']['active'] or not s['envelope']['enabled']):
        raise TransferError('Healthy stationary feedback and active workspace required.')
    if not 27.98<=r['external_axes']['E1']<=28.05:raise TransferError('Jaws must remain open.')
    source=old['candidate_endpoint'];dx=source['X']-cfg['base_x_mm'];dy=source['Y']-cfg['base_y_mm']
    scale=5/math.hypot(dx,dy)
    goal=dict(source,X=source['X']+dx*scale,Y=source['Y']+dy*scale)
    if any(abs(r['pose_mm'][k]-goal[k])>.05 for k in ('X','Y','Z','Rz')):
        raise TransferError('Measured endpoint does not match the requested 5 mm correction.')
    hover={k:goal[k] for k in ('X','Y','Z','Rz')};hover['Z']=300.
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    q=check_path(r['pose_mm'],hover,r['joints'],cfg,env)
    folder=pickup.ROOT/'operator_ui/reports/projected_alignment';stamp=str(time.time_ns())
    def write(name,data):
        path=folder/(name+'_'+stamp+'.json')
        path.write_text(json.dumps(data,indent=2),encoding='utf-8')
        return path.relative_to(pickup.ROOT).as_posix(),pickup.sha(path.read_bytes())
    backup,backup_hash=write('profile_before_additional_outward_5mm',old)
    record=dict(at=time.time(),operator_request='Additional 5 mm outward with jaws open, to equalize observed 20/30 mm gaps to 25/25 mm; save for future descent.',
        direction='away_from_robot_base',additional_distance_mm=5,
        total_outward_distance_from_fresh_alignment_mm=7,
        base_mm=dict(X=cfg['base_x_mm'],Y=cfg['base_y_mm']),
        source_profile_sha256=digest,source_endpoint=source,commanded_endpoint=goal,
        measured_endpoint=r['pose_mm'],measured_e1_mm=r['external_axes']['E1'],
        correction_speed=5,arrival_verified=True,visual_alignment_accepted=False,
        future_hover=hover,vertical_descent_replayed=False,
        jaw_sequence='Operator confirmed: open above plate before lowering. Existing descent verifies E1=28 mm at Z300 before lowering.',
        controller_errors=r['errors'],grip_executed=False)
    report,report_hash=write('additional_outward_5mm',record)
    approval,approval_hash=write('outward_5mm_trial_authorization',dict(
        visual_alignment_accepted=False,supervised_open_claw_trial_authorized=True,
        alignment_pose_mm=hover,operator_feedback=record['operator_request'],
        correction_evidence=report,correction_sha256=report_hash,
        descent_accepted=False,grip_verified=False))
    candidate=deepcopy(old)
    for key in ('lateral_correction','lateral_correction_sha256','descent_acceptance','descent_acceptance_sha256'):
        candidate.pop(key,None)
    candidate.update(acceptance=approval,acceptance_sha256=approval_hash,
        alignment_pose_mm=hover,candidate_endpoint=goal,
        descent_status='pending_supervised_open_claw_trial',
        additional_outward_correction=report,additional_outward_correction_sha256=report_hash,
        previous_profile=backup,previous_profile_sha256=backup_hash,
        jaw_sequence='Open to E1=28 mm at Z300 before lowering; verify opening before descent.',
        total_outward_correction_mm=7,inward_correction_already_applied=False,
        outward_correction_already_applied=True)
    candidate_path,_=write('outward_5mm_candidate_profile',candidate)
    verified,new_digest=pickup.load(pickup.ROOT/candidate_path)
    with patch.object(pickup,'load',return_value=(verified,new_digest)):
        target=pickup.target(trial=True)
        plan=pickup.descent_plan(hover,q,target,cfg,env,band_floor())
    if plan['legs']:raise TransferError('Additional offset must be applied before descent, not twice.')
    write('outward_5mm_descent_plan',dict(plan=plan,profile_sha256=new_digest,
        future_path_physical_trial_pending=True,grip_authorized=False))
    temp=pickup.PROFILE.with_suffix('.tmp')
    temp.write_bytes((pickup.ROOT/candidate_path).read_bytes());temp.replace(pickup.PROFILE)
    print(json.dumps(dict(saved=True,report=report,profile_sha256=new_digest,
        measured_pose=r['pose_mm'],endpoint=goal,hover=hover,
        claw_open_mm=r['external_axes']['E1'],future_descent_replayed=False)))

if __name__=='__main__':main()
