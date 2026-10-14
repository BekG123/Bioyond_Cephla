"""Supervised Wide two-circle teach convergence, at most three moves.
Original teach.solve math; bounded physical steps through the existing GUI.
No enable/restart/grip/target-depth descent; camera-height adjustment only.
"""
import json
import math
import urllib.request
import teach
from find_from_home_step import api, BASE
from autonomy import check_path, ensure_arrival, TransferError, wrap
from sequences import get_robot_params

def ready():
    s=api('/state'); r=s['robot']
    if (not r.get('connected') or not r.get('enabled') or r.get('errors')
        or s['sequence']['active'] or not s['envelope']['enabled']
        or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running'
        or not r['lua_app_initialized']):
        raise TransferError('not ready for supervised disk Find')
    return s

def measure():
    with urllib.request.urlopen(BASE+'/frame',timeout=10) as response:
        if response.headers.get('X-Error'):
            raise TransferError('camera error')
        response.read()
    s=ready()
    if s['camera']['error'] or s['camera']['age_s']>2:
        raise TransferError('fresh camera frame required')
    path=api('/camera/snapshot',{})['path']; p=s['robot']['pose_mm']
    a=teach.solve(path,p['X'],p['Y'],p['Z'],p['Rz'],force_cfg='Wide')
    if not a.get('detected'):
        raise TransferError('two-circle disk lost; no recovery/search motion')
    print(json.dumps(dict(pose=p,image=path,solve=a)),flush=True)
    return s,a

if __name__=='__main__':
    ok,output=teach.selftest()
    if not ok:
        raise TransferError(output)
    s,a=measure()
    for _ in range(3):
        p=s['robot']['pose_mm']; end={k:p[k] for k in ('X','Y','Z','Rz')}
        if a['xy_err_mm']<0.3 and a['rz_err_deg']<0.2 and a['z_err_mm']<0.3:
            print('CONVERGED. No grasp alignment, descent or grip.',flush=True)
            break
        delta=wrap(a['move_xyrz'][3]-p['Rz'])
        if abs(delta)>=0.2:
            if p['Z']<299.99:
                end['Z']=min(300,p['Z']+10)
            else:
                end['Rz']=p['Rz']+max(-5,min(5,delta))
        else:
            dx=a['move_xyrz'][0]-p['X']; dy=a['move_xyrz'][1]-p['Y']
            d=math.hypot(dx,dy)
            if a['xy_err_mm']>=0.3:
                f=min(1,10/max(d,1e-9)); end['X']+=dx*f; end['Y']+=dy*f
            elif a['z_err_mm']>=0.3:
                end['Z']+=max(-5,min(5,a['move_z'][2]-p['Z']))
        if not 250<=end['Z']<=305:
            raise TransferError('outside authorized viewing-height corridor')
        env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
        check_path(p,end,s['robot']['joints'],get_robot_params(),env)
        result=api('/move',dict(x=end['X'],y=end['Y'],z=end['Z'],rz=end['Rz'],speed=5,interpolation='linear'))
        ensure_arrival(result['pose_after'],end)
        ensure_arrival(ready()['robot']['pose_mm'],end)
        s,a=measure()
