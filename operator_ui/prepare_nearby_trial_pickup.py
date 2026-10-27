"""Offline plate-relative adjustment for the new placement; no motion."""
import json,math,time
from projected_pickup import ROOT,load,sha
from autonomy import check_path,wrap

def main():
    folder=ROOT/'operator_ui/reports/projected_alignment'
    source=folder/'prepared_repeat1_reseated_3p9_20261027.json'
    observed=folder/'prepared_squid_nearby_20261027T1200.json'
    profile,digest=load()
    if digest!='9bc3a4319cbb3f8df7804879f9f0ce81a3200c9297d84a85f690b29e7ec5e054':raise RuntimeError('Profile changed.')
    prior=json.loads(source.read_bytes())['route']['target']
    measured=json.loads(observed.read_bytes());target=measured['route']['target']
    endpoint=profile['candidate_endpoint'];yaw=wrap(target['rz']-prior['rz']);angle=math.radians(yaw)
    dx,dy=endpoint['X']-prior['x'],endpoint['Y']-prior['y']
    goal=dict(endpoint,X=target['x']+math.cos(angle)*dx-math.sin(angle)*dy,
        Y=target['y']+math.sin(angle)*dx+math.cos(angle)*dy,Rz=endpoint['Rz']+yaw)
    observation=json.loads((folder/'manual_repeat_observation_1793102455992381400.json').read_bytes())
    state=observation['events'][-1]['state'];robot=state['robot']
    cfg=json.loads((ROOT/'operator_ui/robot_params.json').read_bytes())
    env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    points=measured['route']['waypoints']+[dict(goal,Z=300.),dict(goal,Z=goal['Z']+20),goal]
    pose,joints=robot['pose_mm'],robot['joints'];checked=[]
    for point in points:
        joints=check_path(pose,point,joints,cfg,env);checked.append(dict(pose=point,joints=joints));pose=point
    result=dict(at=time.time(),status='offline_proposal_requires_supervised_open_claw_trial',
        source_profile_sha256=digest,source_endpoint=endpoint,proposed_endpoint=goal,
        placement_delta_mm=math.hypot(target['x']-prior['x'],target['y']-prior['y']),yaw_delta_deg=yaw,
        method='Rigid 2D transform of the accepted repeat-1 jaw offset to the fresh plate pose; no cumulative correction.',
        source_alignment_reference=source.relative_to(ROOT).as_posix(),source_sha256=sha(source.read_bytes()),
        observation=observed.relative_to(ROOT).as_posix(),observation_sha256=sha(observed.read_bytes()),
        checked=checked,ik_passed=True,motion_started=False,profile_changed=False,
        jaws_open_before_lowering_mm=28,grip_authorized=False,inspection_before_grip=True)
    path=folder/'squid_nearby_pickup_adjustment_20261027.json'
    with path.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(dict(report=str(path),endpoint=goal,placement_delta_mm=result['placement_delta_mm'],yaw_delta_deg=yaw,ik_passed=True)))

if __name__=='__main__':main()
