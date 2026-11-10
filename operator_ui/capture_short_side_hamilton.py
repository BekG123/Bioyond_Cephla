"""Capture the operator-positioned site-4 endpoint; no robot motion or mode change."""
import argparse
import hashlib
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_alignment_trial import FOLDER

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--positioned-and-stopped',action='store_true')
    args=parser.parse_args()
    if not args.positioned_and_stopped:raise RuntimeError('Wait for operator to position at site 4 and request capture')
    path=FOLDER/'taught_hamilton_site4_short_side.json'
    if path.exists():raise RuntimeError('Site-4 target already captured; preserve before reteaching')
    acceptance=(FOLDER/'accepted_short_side25.json').read_bytes()
    s=api('state')
    if not s['robot'].get('connected') and not s['sequence']['active']:
        assert api('connect',{'ip':'192.168.201.220'})['ok']
    samples=[]
    for _ in range(3):
        s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
        if s['sequence']['active'] or not r.get('connected') or not r.get('ok') or r.get('errors') or any(n[k] for k in ('moving','error','emergency')):raise RuntimeError('Stationary fault-free feedback required')
        if samples:near(r['pose_mm'],samples[0]['robot']['pose_mm'],.05)
        samples.append(dict(at=time.time(),robot=r,native=n));time.sleep(.2)
    record=dict(role='operator_taught_Hamilton_site4_short_side_endpoint',status='captured_pending_route_review',
        target={k:r['pose_mm'][k] for k in ('X','Y','Z','Rz')},joints=r['joints'],external_axes=n['external_axes'],
        samples=samples,config=api('robot_params'),envelope=s['envelope'],
        pickup_reference_sha256=hashlib.sha256(acceptance).hexdigest(),
        existing_hamilton_route_replaced=False,route_tested=False,seating_verified=False)
    with path.open('x') as f:json.dump(record,f,indent=2)
    print(json.dumps(dict(path=str(path),target=record['target']),indent=2))

if __name__=='__main__':main()
