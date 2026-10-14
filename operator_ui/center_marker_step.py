"""Bounded supervised ID-1 centering at the existing height/yaw only.
No enabling, search, descent, gripper actuation, or error recovery.
"""
import json
import math
import urllib.request
import aruco
from autonomy import check_path, ensure_arrival, TransferError
from sequences import get_robot_params
from find_from_home_step import api, ready, BASE

def measure():
    with urllib.request.urlopen(BASE+'/frame',timeout=10) as response:
        if response.headers.get('X-Error'):
            raise TransferError('camera error')
        response.read()
    s=ready()
    if s['camera']['error'] or s['camera']['age_s']>2:
        raise TransferError('camera is stale')
    path=api('/camera/snapshot',{})['path']
    p=s['robot']['pose_mm']
    a=aruco.solve(path,p['X'],p['Y'],p['Z'],p['Rz'],marker_id=1)
    if not a.get('detected'):
        raise TransferError('ID 1 lost/ambiguous; stop, no blind search')
    v=aruco.view_center_world(p['X'],p['Y'],p['Rz'],a['H_mm'])
    delta=(a['marker_world'][0]-v[0],a['marker_world'][1]-v[1])
    print(json.dumps(dict(pose=p,center_px=a['center_px'],error_mm=math.hypot(*delta),H_mm=a['H_mm'],image=path)),flush=True)
    return s,delta

if __name__ == '__main__':
    s,delta=measure()
    for _ in range(3):
        error=math.hypot(*delta)
        if error<=1:
            print('CENTERED; stopped without descent or grip.',flush=True)
            break
        p=s['robot']['pose_mm']
        fraction=min(0.7,10/error)
        end=dict(X=p['X']+delta[0]*fraction,Y=p['Y']+delta[1]*fraction,Z=291.895,Rz=6.794)
        env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
        check_path(p,end,s['robot']['joints'],get_robot_params(),env)
        result=api('/move',dict(x=end['X'],y=end['Y'],z=end['Z'],rz=end['Rz'],speed=5,interpolation='linear'))
        ensure_arrival(result['pose_after'],end)
        ensure_arrival(ready()['robot']['pose_mm'],end)
        s,delta=measure()
        if math.hypot(*delta)>error+2:
            raise TransferError('centering error grew; stop and inspect model')
