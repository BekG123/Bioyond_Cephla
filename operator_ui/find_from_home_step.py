"""Operator-supervised, bounded camera approach via the existing console.

One invocation: at most three 10 mm steps, stop on any marker sighting.
Never enables, restarts, grips, descends or retries a failed command.
Specific commissioned 2026-09-14 route only, not a general search tool.
"""
import json
import math
import urllib.request
import aruco
from autonomy import check_path, ensure_arrival, TransferError
from sequences import get_robot_params

BASE = 'http://127.0.0.1:5002'

def api(path, body=None):
    req = urllib.request.Request(BASE+path, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.load(response)
    if result.get('ok') is False or result.get('recovered'):
        raise TransferError(str(result))
    return result

def ready():
    s = api('/state')
    r = s['robot']
    if not r.get('connected') or not r.get('enabled') or r.get('errors') or s['sequence']['active']:
        raise TransferError('robot not ready or sequence active')
    if r['control_mode']['mode'] != 'auto' or r['program_state']['state'] != 'running' or not r['lua_app_initialized']:
        raise TransferError('robot not in auto/running/initialized')
    if not s['envelope']['enabled']:
        raise TransferError('envelope disabled')
    p=r['pose_mm']
    if abs(p['Z']-291.895)>0.5 or abs(p['Rz']-6.794)>0.1:
        raise TransferError('pose changed from authorized height/wrist')
    return s

def capture():
    with urllib.request.urlopen(BASE+'/frame',timeout=10) as response:
        if response.headers.get('X-Error'):
            raise TransferError('camera error')
        response.read()
    s=ready()
    if s['camera']['error'] or s['camera']['age_s']>2:
        raise TransferError('fresh camera frame unavailable')
    path=api('/camera/snapshot',{})['path']
    markers=aruco.W.detect_sized(path)
    print(json.dumps({'pose':s['robot']['pose_mm'],'markers':markers,'image':path}),flush=True)
    return bool(markers)

if __name__ == '__main__':
    if capture():
        raise SystemExit(0)
    for _ in range(3):
        s=ready(); p=s['robot']['pose_mm']
        if p['X']<199.99 and abs(p['Y']-0.553)<0.1:
            tx,ty=200.,0.553
        else:
            tx,ty=305.871,54.806
        d=math.hypot(tx-p['X'],ty-p['Y'])
        if d<0.1:
            print('End of authorized route; no marker found. No sweep beyond it.',flush=True)
            break
        f=min(1,10/d)
        end=dict(X=p['X']+f*(tx-p['X']),Y=p['Y']+f*(ty-p['Y']),Z=291.895,Rz=6.794)
        env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
        check_path(p,end,s['robot']['joints'],get_robot_params(),env)
        result=api('/move',dict(x=end['X'],y=end['Y'],z=end['Z'],rz=end['Rz'],speed=5,interpolation='linear'))
        ensure_arrival(result['pose_after'],end)
        ensure_arrival(ready()['robot']['pose_mm'],end)
        if capture():
            print('Marker visible. STOP; no further motion.',flush=True)
            break
