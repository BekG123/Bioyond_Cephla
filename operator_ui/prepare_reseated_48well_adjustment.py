"""Offline SE(2) transfer of taught jaw offset to the reseated plate; no motion."""
import json
import math
import time
from projected_pickup import ROOT,load,sha
from autonomy import check_path


def main():
    folder=ROOT/'operator_ui/reports/projected_alignment'
    source=folder/'alignment_outward_trial_20261027.json'
    observed=folder/'prepared_repeat1_reseated_3p9_20261027.json'
    profile,digest=load();prior=json.loads(source.read_bytes())['source_alignment_pose']
    measured=json.loads(observed.read_bytes());target=measured['route']['target']
    endpoint=profile['candidate_endpoint'];angle=math.radians(target['rz']-prior['Rz'])
    dx,dy=endpoint['X']-prior['X'],endpoint['Y']-prior['Y']
    goal=dict(endpoint,X=target['x']+math.cos(angle)*dx-math.sin(angle)*dy,
        Y=target['y']+math.sin(angle)*dx+math.cos(angle)*dy,
        Rz=endpoint['Rz']+target['rz']-prior['Rz'])
    # Validate against the recorded healthy observation snapshot, without
    # connecting to hardware or changing the active taught pickup profile.
    observation=json.loads((folder/'manual_repeat_observation_1793095257989630900.json').read_bytes())
    state=observation['events'][-1]['state'];robot=state['robot']
    cfg=json.loads((ROOT/'operator_ui/robot_params.json').read_bytes())
    env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    points=measured['route']['waypoints']+[dict(goal,Z=300),dict(goal,Z=goal['Z']+20),goal]
    pose,joints=robot['pose_mm'],robot['joints'];checked=[]
    for point in points:
        joints=check_path(pose,point,joints,cfg,env);checked.append(dict(pose=point,joints=joints));pose=point
    result=dict(at=time.time(),status='offline_proposal_requires_supervised_open_claw_trial',
        source_profile_sha256=digest,source_endpoint=endpoint,proposed_endpoint=goal,
        placement_delta_mm=math.hypot(target['x']-prior['X'],target['y']-prior['Y']),
        yaw_delta_deg=target['rz']-prior['Rz'],
        method='Rigid 2D transform preserves taught plate-relative jaw offset; no cumulative correction.',
        source_alignment_reference=source.relative_to(ROOT).as_posix(),source_sha256=sha(source.read_bytes()),
        observation=observed.relative_to(ROOT).as_posix(),observation_sha256=sha(observed.read_bytes()),
        checked=checked,ik_passed=True,motion_started=False,profile_changed=False,
        jaws_open_before_lowering_mm=28,grip_authorized=False,inspection_before_grip=True)
    path=folder/'reseated_repeat1_adjustment_proposal_20261027.json'
    with path.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(dict(report=str(path),endpoint=goal,ik_passed=True,motion_started=False)))


if __name__=='__main__':main()
