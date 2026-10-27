"""Read-only proposal for one fixed-X workspace re-entry, then standard Home."""
import json,time
from projected_pickup import ROOT
from proof_lift_plate import api,near,write
from autonomy import check_path
from researcher_home import queued_station_stages

def main():
    state=api('state');r=state['robot']
    if not r.get('connected') or not r.get('ok') or r.get('errors') or state['sequence']['active']:
        raise RuntimeError('Healthy stationary connected state required.')
    start={k:r['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    near(start,dict(X=176.639,Y=-5.813,Z=309.781,Rz=-6.277),.05)
    cfg=api('robot_params');env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    if env!={'X':(200.,450.),'Y':(-250.,380.),'Z':(70.,400.)} or not state['envelope']['enabled']:
        raise RuntimeError('Workspace changed.')
    target={**start,'X':205.}
    # An explicit proposed recovery corridor, NOT a persisted workspace change.
    # It permits only the existing out-of-box start and monotonically increasing
    # X to an in-box target; other coordinates remain fixed.
    corridor={**env,'X':(start['X'],205.)}
    q=check_path(start,target,r['joints'],cfg,corridor)
    home=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
    stages=queued_station_stages(target,home,q,cfg,env)
    previous=target;checked=[dict(pose=target,joints=q)]
    for stage in stages:
        points=stage['points'] if stage['kind']=='queue' else [{**previous,'Rz':stage['rz']}]
        for point in points:
            q=check_path(previous,point,q,cfg,env)
            q['J1']=r['joints']['J1']+point['Z']-start['Z']
            if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise RuntimeError('Joint travel limit.')
            checked.append(dict(pose=point,joints=dict(q)));previous=point
    result=dict(at=time.time(),status='prepared_pending_specific_reentry_clearance',
        start=start,state=state,proposed_reentry=target,speed=5,cfg=cfg,
        normal_envelope=env,proposed_reentry_corridor=corridor,normal_home_stages=stages,checked=checked,
        hardware_commands_sent=False,workspace_changed=False,
        authorization_required='Specific empty-gripper reentry sweep and subsequent Home route clearance; E-stop supervision.',
        reason='Current X176.639 is outside normal X>=200; request explicit recovery approval instead of disabling the workspace.')
    path=ROOT/'operator_ui/reports/projected_alignment/home_reentry_20261027T1156.json'
    if path.exists():raise RuntimeError('Proposal already recorded.')
    write(path,result)
    print(json.dumps(dict(path=str(path),start=start,reentry=target,home_stages=stages,ik_passed=True)))

if __name__=='__main__':main()
