"""Capture the manually taught clearance waypoint. Never command motion."""
import hashlib
import json
import time
import argparse
from proof_lift_plate import api,near
from draggo import DragGoRPC
from hamilton_short_side_trial import FOLDER,reference,PLAN_SHA

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision',choices=('01','02'),default='01')
revision=parser.parse_args().revision
path=FOLDER/('taught_hamilton_short_side_turning'+revision+'.json')
if path.exists():raise RuntimeError('Waypoint already saved; preserve before reteaching')
p,parent=reference();s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok']
samples=[]
for _ in range(3):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    if s['sequence']['active'] or not r.get('connected') or not r.get('ok') or n['moving']:
        raise RuntimeError('Stationary connected feedback required for teaching')
    if samples:near(r['pose_mm'],samples[0]['robot']['pose_mm'],.05)
    samples.append(dict(at=time.time(),robot=r,native=n));time.sleep(.2)
record=dict(role='operator_taught_Hamilton_short_side_turning_clearance',
    status='captured_for_offline_route_revision',target={k:r['pose_mm'][k] for k in ('X','Y','Z','Rz')},
    joints=r['joints'],external_axes=n['external_axes'],samples=samples,
    config=api('robot_params'),envelope=s['envelope'],parent_plan_sha256=PLAN_SHA,
    revision=revision,
    feedback=('After the loaded approach collision, operator taught a new turning pose; pickup must travel directly to site 4 without visiting Home.' if revision=='02' else 'After the direct reverse collision, operator manually positioned the arm at the ideal turning coordinate and requested forward/reverse route revision.'),
    faults_cleared_by_this_script=False,motion_commanded=False,route_tested=False,
    home_source_sha256=parent['home_sha256'],endpoint_source_sha256=parent['taught_sha256'])
with path.open('x') as f:json.dump(record,f,indent=2)
print(json.dumps(dict(path=str(path),target=record['target'],joints=record['joints'],errors=r['errors']),indent=2))
