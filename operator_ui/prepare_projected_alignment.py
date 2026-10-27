"""Capture and prepare a 48-well alignment route. Never sends motion commands."""
import json
import argparse
import time
import hashlib
from urllib.request import Request, urlopen
import cv2
import numpy as np
from projected_alignment import ROOT, perception_at_height, plan, target_from_mark
from projected_disk_trial import same_pose
from autonomy import TransferError, wrap

def request(path, body=None):
    data=None if body is None else json.dumps(body).encode()
    with urlopen(Request('http://127.0.0.1:5002'+path,data=data,
                        headers={'Content-Type':'application/json'}),timeout=10) as response:
        raw=response.read()
        if response.headers.get('X-Error'):
            raise TransferError(response.headers['X-Error'])
        return raw

def state():
    s=json.loads(request('/state'))
    if (s['sequence']['active'] or not s['robot'].get('connected')
            or not s['robot'].get('ok') or s['robot'].get('errors')):
        raise TransferError('Healthy idle controller feedback required.')
    return s

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='operator_ui/reports/projected_alignment/prepared_route_'+time.strftime('%Y%m%d_%H%M%S')+'.json')
    args=parser.parse_args()
    before=state();pose=before['robot']['pose_mm']
    p,reference,provenance=perception_at_height()
    if abs(pose['Z']-reference['observation_z_mm'])>.1:
        raise TransferError('Not at the verified observation height.')
    measurements=[];image_paths=[];all_hashes=[]
    for batch in range(3):
        frames=[];hashes=[]
        for _ in range(5):
            request('/frame')
            if state()['camera'].get('age_s',999)>.8:
                raise TransferError('Camera frame is stale.')
            snap=json.loads(request('/camera/snapshot',{}))
            if not snap.get('ok'):raise TransferError(snap.get('error','Snapshot failed.'))
            frame=cv2.imread(snap['path']);frames.append(frame);image_paths.append(snap['path'])
            hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
            if not same_pose(pose,state()['robot']['pose_mm']):
                raise TransferError('Arm moved during preparation.')
            time.sleep(.3)
        if len(set(hashes))<3:raise TransferError('Insufficient distinct camera frames.')
        measurement=p.measure(np.median(frames,axis=0).astype(np.uint8),pose)
        measurements.append(measurement);all_hashes.append(hashes)
        print(json.dumps(dict(batch=batch+1,wells=measurement['tracking']['supported_wells'],
            xy=measurement['error_xy_mm'],mark=measurement['mark'],
            composed_uncertainty_px=measurement['tracking']['disk_group_spread_px'])),flush=True)
    targets=[target_from_mark(pose,m,p.cfg) for m in measurements]
    if any(np.hypot(a['x']-b['x'],a['y']-b['y'])>.5 or abs(wrap(a['rz']-b['rz']))>.2
           for a in targets for b in targets):raise TransferError('Alignment targets disagree.')
    params=json.loads((ROOT/'operator_ui/robot_params.json').read_text())
    envelope={k:(before['envelope'][k]['min'],before['envelope'][k]['max']) for k in ('X','Y','Z')}
    route=plan(pose,measurements[-1],p.cfg,before['robot']['joints'],params,envelope)
    report=dict(timestamp=time.time(),motion_started=False,start=pose,route=route,
        reference=provenance,measurements=measurements,images=image_paths,image_hashes=all_hashes)
    folder=ROOT/'operator_ui/reports/projected_alignment';folder.mkdir(parents=True,exist_ok=True)
    out=ROOT/args.output
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(out),start=pose,route=route)),flush=True)

if __name__=='__main__':main()
