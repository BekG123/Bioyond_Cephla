"""Read-only pose capture and offline validation; never sends robot commands."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from urllib.request import urlopen
from unittest.mock import patch

from autonomy import check_path, wrap
from pick_and_hold.Descend import correction

ROOT=Path(__file__).resolve().parents[1]
def read_state():
    with urlopen('http://127.0.0.1:5002/state',timeout=5) as response:
        return json.load(response)
def save(path, value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')

if __name__=='__main__':
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    if len(sys.argv)>1:
        folder=(ROOT/sys.argv[1]).resolve()
        samples=json.loads((folder/'samples.json').read_text())
        old_raw=(folder/'previous_profile.json').read_bytes()
        stamp=json.loads((folder/'endpoint_record.json').read_text())['captured_at']
        if correction.PROFILE.read_bytes()!=old_raw:raise RuntimeError('Active profile changed; review before applying captured correction.')
    else:
        folder=ROOT/'operator_ui/demonstrations'/('descent_endpoint_adjustment_'+stamp)
        folder.mkdir()
        samples=[]
        for _ in range(8):
            samples.append(read_state());time.sleep(.2)
        save(folder/'samples.json',samples)
        old_raw=correction.PROFILE.read_bytes()
        (folder/'previous_profile.json').write_bytes(old_raw)
    old=json.loads(old_raw)
    for state in samples:
        if not state['robot'].get('connected') or not state['robot'].get('ok') or state['sequence'].get('active'):
            raise RuntimeError('Pose feedback unavailable or sequence active; samples retained only.')
    pose={key:round(statistics.median(s['robot']['pose_mm'][key] for s in samples),3) for key in ('X','Y','Z','Rz')}
    spread={key:max(s['robot']['pose_mm'][key] for s in samples)-min(s['robot']['pose_mm'][key] for s in samples) for key in pose}
    if max(spread.values())>.05:raise RuntimeError('Endpoint not stationary; samples retained only.')
    delta={key:round(pose[key]-old['endpoint'][key],3) for key in pose}
    delta['Rz']=round(wrap(delta['Rz']),3)
    source=ROOT/'operator_ui/demonstrations/position_grip/5e843bc519c448289686677a133a4c64.json'
    trial=json.loads(source.read_text())
    prior=trial['descent']['descent_result']['descent_correction']
    record=dict(schema='cephla.manual-descent-endpoint.v1',captured_at=stamp,
        feedback='Operator pushed arm slightly forward, reported improvement, requested recording and inclusion in final descent.',
        endpoint=pose,delta_from_previous_taught_endpoint=delta,spread=spread,
        previous_profile_sha256=hashlib.sha256(old_raw).hexdigest(),
        completed_descent_pose=trial['descent']['pose_mm'],
        delta_from_completed_descent={k:round(pose[k]-trial['descent']['pose_mm'][k],3) for k in pose},
        robot_errors=samples[-1]['robot']['errors'],enabled=samples[-1]['robot']['enabled'],
        e1_mm=samples[-1]['robot']['external_axes']['E1'],
        physical_replay_validated=False,
        interpretation='Absolute taught endpoint for this unchanged plate. XY/yaw adjustment at hover, then pure Z. E1 observation is not a new grip command. Capture made with servos disabled and existing external-axis fault; no error reset or motion.')
    evidence=folder/'endpoint_record.json';save(evidence,record)
    candidate=deepcopy(old)
    candidate.update(id='two_disk_manual_endpoint_'+stamp,endpoint=pose,
        evidence=evidence.relative_to(ROOT).as_posix(),evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
        note='Operator-requested manual refinement of the exact endpoint. Apply at hover before vertical descent. Not hardware-replayed; controller fault must be resolved before execution. No cumulative offsets.')
    candidate_path=folder/'candidate_profile.json';save(candidate_path,candidate)
    cfg=json.loads((ROOT/'operator_ui/robot_params.json').read_text(encoding='utf-8-sig'))
    envelope=samples[-1]['envelope']
    if 'box' in envelope:envelope=envelope['box']
    envelope={key:(envelope[key]['min'],envelope[key]['max']) if isinstance(envelope[key],dict) else envelope[key] for key in ('X','Y','Z')}
    robot=samples[-1]['robot']
    start=prior['start']
    joints=check_path(pose,start,robot['joints'],cfg,envelope)
    with patch.object(correction,'PROFILE',candidate_path):
        plan=correction.corrected_plan(start,joints,prior['original_target'],cfg,envelope,66)
    save(folder/'offline_plan.json',dict(ok=True,plan=plan,physical_motion=False))
    temp=correction.PROFILE.with_suffix('.tmp')
    temp.write_bytes(candidate_path.read_bytes());temp.replace(correction.PROFILE)
    print(json.dumps(dict(folder=str(folder),endpoint=pose,delta=delta,spread=spread,offline_validation=True,profile_updated=True)))
