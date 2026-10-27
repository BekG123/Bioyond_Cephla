"""Prepare an immutable Home connection for review. GET requests only; no motion."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from autonomy import check_path
from researcher_home import queued_station_stages, HOME_SPEED

ROOT=Path(__file__).resolve().parent


def get(path):
    with urlopen('http://127.0.0.1:5002'+path,timeout=10) as response:
        return json.load(response)


def prepare():
    state,cfg=get('/state'),get('/robot_params')
    robot=state['robot']
    if state['sequence']['active'] or not robot.get('ok') or not robot.get('connected') or robot.get('errors'):
        raise RuntimeError('A healthy stationary arm is required for review.')
    if not state['envelope']['enabled']:
        raise RuntimeError('Workspace must be enabled.')
    raw=(ROOT/'points.json').read_bytes()
    data=json.loads(raw.decode('utf-8-sig'))
    point=data['points'][data['roles']['home']]
    home=dict(X=point['x'],Y=point['y'],Z=point['z_grip'],Rz=point['rz'])
    target_id=hashlib.sha256(json.dumps(home,sort_keys=True).encode()).hexdigest()
    envelope={a:[state['envelope'][a]['min'],state['envelope'][a]['max']] for a in ('X','Y','Z')}
    pose={k:robot['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    stages=queued_station_stages(pose,home,robot['joints'],cfg,envelope)
    previous,q=pose,dict(robot['joints'])
    checked=[]
    for stage in stages:
        points=stage['points'] if stage['kind']=='queue' else [{**previous,'Rz':stage['rz']}]
        for end in points:
            next_q=check_path(previous,end,q,cfg,envelope)
            next_q['J1']=robot['joints']['J1']+end['Z']-pose['Z']
            if not 0<=next_q['J1']<=400 or abs(next_q['J3'])>180:
                raise RuntimeError('Joint travel exceeds the configured limits.')
            checked.append(dict(kind=stage['kind'],pose=end,joints=next_q))
            previous,q=end,next_q
    result=dict(schema='cephla.alignment-home-review.v1',created_at=datetime.now(timezone.utc).isoformat(),
        start=pose,start_joints=robot['joints'],observed_e1=robot['external_axes'].get('E1'),
        home=home,target_id=target_id,points_sha256=hashlib.sha256(raw).hexdigest(),
        stages=stages,checked_waypoints=checked,config=cfg,envelope=envelope,
        translation_speed=HOME_SPEED,wrist_speed=30,ik_and_limits_passed=True,
        execution_authorized=False,physical_clearance_verified=False,
        requires=['Empty gripper confirmed','Wrist sweep at Z300 and across-to-Home corridor clear',
                  'Final lowering to saved Home clear','Arm released, hands clear, E-stop supervised'],
        policy='One reviewed connection only; does not enable arbitrary Home fallbacks.')
    folder=ROOT/'reports/alignment_home'
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_review.json')
    with path.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(path=str(path),start=pose,home=home,stages=stages,
                         translation_speed=HOME_SPEED,wrist_speed=30,final_joints=q,
                         ik_and_limits_passed=True),indent=2))


if __name__=='__main__':prepare()
