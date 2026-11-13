"""Offline continuous turn-in candidate; retain Z77 crossing and seating."""
import hashlib
import json
from pathlib import Path
from copy import deepcopy
from plan_short_side_hamilton import validate

FOLDER=Path(__file__).resolve().parent/'reports/plate_session/cellvis24_validation'
SOURCE=FOLDER/'hamilton_rack_loaded_plan.json'
OUTPUT=FOLDER/'hamilton_rack_continuous_turn_plan.json'
SOURCE_SHA='68eb9be943b50dbfb7b0aad1d53d94564d2c829825d9827ea66d08fd6f33259a'

def build():
    raw=SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA:raise ValueError('Loaded rack baseline changed')
    p=json.loads(raw);r=p['routes']['forward'];start=r['start'];turn=r['points'][1]
    # Same line and yaw slope through both command halves. Keep two halves
    # to unambiguously command the taught -180.9-degree winding, not +179.1.
    mid={k:round((start[k]+turn[k])/2,2) for k in ('X','Y','Z','Rz')}
    points=[mid]+deepcopy(r['points'][1:]);cfg=p['config'];env=p['station_envelope']
    v=validate(start,points,r['start_joints'],cfg,env,r['validation']['endpoint_joints'])
    back=list(reversed([start]+points))[1:]
    rv=validate(points[-1],back,v['endpoint_joints'],cfg,env,r['start_joints'])
    if not v['workspace_valid'] or not rv['workspace_valid']:raise ValueError('Workspace violation')
    p['routes']['forward'].update(points=points,validation=v)
    p['routes']['reverse'].update(points=back,start_joints=v['endpoint_joints'],validation=rv)
    p.update(parent_loaded_sha256=SOURCE_SHA,status='offline_checked_new_turn_sweep_pending_physical_trial',
             operator_request='Combine the Hamilton turn segments into continuous motion',
             motion_sent=False,physical_clearance_verified=False)
    return p

if __name__=='__main__':
    p=build()
    with OUTPUT.open('x') as f:json.dump(p,f,indent=2,allow_nan=False)
    print(json.dumps(dict(path=str(OUTPUT),sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),points=p['routes']['forward']['points'])))
