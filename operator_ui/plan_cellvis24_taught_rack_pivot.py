"""Offline rack pivot revision after operator correction. No robot access."""
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from plan_short_side_hamilton import validate

FOLDER=Path(__file__).resolve().parent/'reports/plate_session/cellvis24_validation'
SOURCE=FOLDER/'hamilton_rack_continuous_turn_plan.json'
SOURCE_SHA='9ddc8b186a3d19a85e6d7901c0994d79e051b07b82667f6cc474e846faae865d'
CAPTURE=FOLDER/'hamilton_taught_turn_1794431728156528700.json'
CAPTURE_SHA='d58b7374ef34a3166b4347806bab1739c1ca4cf414822bdf68ae3de8eb009b4f'
OUTPUT=FOLDER/'hamilton_rack_taught_pivot_plan_v2.json'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def taught():
    if digest(CAPTURE)!=CAPTURE_SHA:raise ValueError('Taught pivot capture changed')
    d=json.loads(CAPTURE.read_bytes())
    for s in d['samples']:
        if s['native']['moving']:raise ValueError('Moving capture')
        if any(abs(s['state']['robot']['pose_mm'][k]-d['pose'][k])>.05 for k in ('X','Y','Z','Rz')):
            raise ValueError('Unstable taught pose')
    return d

def points_for(start,tail):
    d=taught();pivot={k:math.floor(d['pose'][k]*100+.5)/100 for k in ('X','Y','Z','Rz')}
    # Reach operator's clearance location before the wrist sweep. The taught
    # orientation is an intermediate point, preserving the negative winding.
    approach=dict(pivot,Rz=start['Rz'])
    finish=dict(pivot,Rz=tail[0]['Rz'])
    return [approach,pivot,finish,dict(finish,Z=77.0)]+deepcopy(tail)

def build():
    if digest(SOURCE)!=SOURCE_SHA:raise ValueError('Parent candidate changed')
    p=json.loads(SOURCE.read_bytes());r=p['routes']['forward'];start=r['start']
    tail=r['points'][-3:];points=points_for(start,tail)
    v=validate(start,points,r['start_joints'],p['config'],p['station_envelope'],r['validation']['endpoint_joints'])
    back=list(reversed([start]+points))[1:]
    rv=validate(points[-1],back,v['endpoint_joints'],p['config'],p['station_envelope'],r['start_joints'])
    if not v['workspace_valid'] or not rv['workspace_valid']:raise ValueError('Workspace violation')
    # Verify that the commanded pivot follows the operator's taught IK branch.
    d=taught();at_pivot=validate(start,points[:2],r['start_joints'],p['config'],p['station_envelope'],d['joints'])
    r.update(points=points,segment_speeds=[137]*(len(points)-1)+[5],validation=v)
    p['routes']['reverse'].update(start=points[-1],points=back,start_joints=v['endpoint_joints'],
        segment_speeds=[5]+[137]*(len(back)-1),validation=rv)
    p.update(status='offline_checked_taught_pivot_pending_physical_trial',motion_sent=False,
        physical_clearance_verified=False,parent_candidate_sha256=SOURCE_SHA,
        taught_pivot_capture=str(CAPTURE.name),taught_pivot_sha256=CAPTURE_SHA,
        taught_pivot=points[1],taught_pivot_joint_check=at_pivot['endpoint_joint_error'],
        operator_request='More room through rack; reach taught pivot before turning; retain endpoint and one queue',
        failed_parent_run='cellvis24_workflows/c1d0b78a69674a9cae642d05b10200ff/run.json')
    return p

if __name__=='__main__':
    p=build()
    with OUTPUT.open('x') as f:json.dump(p,f,indent=2,allow_nan=False)
    print(json.dumps(dict(path=str(OUTPUT),sha256=digest(OUTPUT),points=p['routes']['forward']['points'],
        forward_length_mm=p['routes']['forward']['validation']['length_mm'],
        forward_joint_ranges=p['routes']['forward']['validation']['joint_ranges'],
        forward_samples=len(p['routes']['forward']['validation']['dense_samples']),
        reverse_samples=len(p['routes']['reverse']['validation']['dense_samples']))))
