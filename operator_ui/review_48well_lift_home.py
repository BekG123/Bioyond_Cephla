"""Read-only review of the requested 5 mm slow lift followed by saved Home."""
import json
import time
from urllib.request import urlopen
from autonomy import check_path, ensure_arrival
from researcher_home import queued_station_stages
import projected_pickup as p


def get(path):
    with urlopen('http://127.0.0.1:5002/'+path,timeout=5) as response:
        return json.load(response)


def main():
    state=get('state');robot=state['robot'];profile,digest=p.load()
    if not robot.get('connected') or not robot.get('ok') or robot.get('errors') or state['sequence']['active']:
        raise p.TransferError('Connected stationary feedback without faults required for review.')
    start=robot['pose_mm'];ensure_arrival(start,profile['candidate_endpoint'])
    cfg=get('robot_params');env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    raw=(p.ROOT/'operator_ui/points.json').read_bytes();points=json.loads(raw.decode('utf-8-sig'))
    saved=points['points'][points['roles']['home']]
    home=dict(X=saved['x'],Y=saved['y'],Z=saved['z_grip'],Rz=saved['rz'])
    lift=dict(start,Z=start['Z']+5.)
    joints=check_path(start,lift,robot['joints'],cfg,env)
    stages=queued_station_stages(lift,home,joints,cfg,env)
    pose=lift;checked=[]
    for stage in stages:
        ends=stage['points'] if stage['kind']=='queue' else [dict(pose,Rz=stage['rz'])]
        for end in ends:
            joints=check_path(pose,end,joints,cfg,env);pose=end
            checked.append(dict(pose=end,joints=joints))
    report=dict(at=time.time(),schema='cephla.48well-lift-home-review.v1',profile_sha256=digest,
        state=state,proof_lift=dict(start=start,target=lift,speed=5),home=home,
        home_stages=stages,checked=checked,home_translation_speed=137,wrist_speed=30,
        points_sha256=p.sha(raw),ik_passed=True,motion_started=False,
        grasp_load_tested=False,allow_program_restart=False,
        blocker='Program stopped following grip settling failure. Startup can reset E1 toward zero; do not restart with plate between jaws.')
    folder=p.ROOT/'operator_ui/reports/projected_alignment'
    path=folder/('even_spacing_lift_home_review_'+str(time.time_ns())+'.json')
    with path.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(dict(report=str(path),lift=lift,home=home,ik_passed=True,
                         program=robot['program_state']['state'],motion_started=False)))


if __name__=='__main__':main()
