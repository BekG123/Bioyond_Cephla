"""Offline loaded Cellvis connector to the pinned Z77 rack corridor."""
import hashlib
import json
import time
from copy import deepcopy
from cellvis24_hamilton_route import reference, PLAN, FOLDER
from hamilton_rack_clearance import fast_reference, FAST_SHA
from plan_short_side_hamilton import validate

OUTPUT=FOLDER/'hamilton_rack_loaded_plan.json'

def build():
    old=reference();rack,_=fast_reference();p=deepcopy(old)
    start=old['routes']['forward']['start'];joints=old['routes']['forward']['start_joints']
    points=deepcopy(rack['forward']['points'])
    if points[-1]!=old['routes']['forward']['points'][-1]:raise ValueError('Station endpoint changed')
    expected=old['routes']['forward']['validation']['endpoint_joints']
    v=validate(start,points,joints,p['config'],p['station_envelope'],expected)
    back=list(reversed([start]+points))[1:]
    rv=validate(points[-1],back,v['endpoint_joints'],p['config'],p['station_envelope'],joints)
    if not v['workspace_valid'] or not rv['workspace_valid']:raise ValueError('Workspace violation')
    p.update(status='offline_checked_loaded_rack_trial_pending',created_at=time.time(),
             parent_cellvis_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),rack_sha256=FAST_SHA,
             motion_sent=False,operator_requested_loaded_trial=True)
    p['routes']={
        'forward':dict(start=start,start_joints=joints,points=points,validation=v,segment_speeds=rack['forward']['segment_speeds']),
        'reverse':dict(start=points[-1],start_joints=v['endpoint_joints'],points=back,validation=rv,segment_speeds=rack['reverse']['segment_speeds'])}
    return p

if __name__=='__main__':
    p=build()
    with OUTPUT.open('x',encoding='utf-8') as f:json.dump(p,f,indent=2,allow_nan=False)
    print(json.dumps(dict(path=str(OUTPUT),sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                         start=p['routes']['forward']['start'],points=p['routes']['forward']['points'])))
