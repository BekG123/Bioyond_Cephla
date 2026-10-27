"""Accepted Hamilton travel evidence; no motion or controller access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from autonomy import TransferError
from scope_step_trial import near

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'reports/trajectory_smoothing/hamilton_reteach_20261026'
HASHES={
    'candidate.json':'4883914f3c350a34eb4f899d8bff20bf9606bd4905c553d7403e22a14f9393bf',
    'forward_speed137_trial.json':'95da1db16afce5066426423ea5f494568cd014b704eb9c7247d964ca98ff9979',
    'reverse_speed137_trial.json':'267ad0976292cef9543778f93572f0a025193826b1db21f22a608e4db45bd81a',
    'operator_acceptance.json':'07411d3bcf7336e365b4df649f9d3a520eae6cff7cf57eca31dde2c995291fa8',
    'reverse_operator_acceptance.json':'8eb9f6d84062142cbefc626a6173a2ce976c377274a0a0ec5ce07aafe8718e27',
}


def evidence():
    records={}
    for name,digest in HASHES.items():
        raw=(FOLDER/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:
            raise TransferError('Accepted Hamilton evidence changed: '+name)
        records[name]=json.loads(raw)
    candidate=records['candidate.json']
    for direction,acceptance in (('forward','operator_acceptance.json'),('reverse','reverse_operator_acceptance.json')):
        trial=records[direction+'_speed137_trial.json'];plan=trial['plan']
        if (trial['status']!='completed' or trial['result'].get('ok') is not True
                or plan['candidate_sha256']!=HASHES['candidate.json'] or plan['speed']!=137
                or [plan['start']]+plan['points']!=candidate['routes'][direction]
                or records[acceptance].get('accepted') is not True
                or records[acceptance]['candidate_sha256']!=HASHES['candidate.json']):
            raise TransferError('Hamilton direction lacks matching accepted completion.')
        near(trial['final_robot']['pose_mm'],candidate['routes'][direction][-1],.05)
    return records


def route(home,envelope,config):
    records=evidence();candidate=records['candidate.json']
    path=candidate['routes']['forward']
    near(home,path[0],.001)
    env={k:list(v) for k,v in envelope.items()}
    if env!=candidate['parent']['envelope']:
        raise TransferError('Accepted Hamilton workspace changed.')
    if config['candidate_sha256']!=HASHES['candidate.json'] or config['pose']!=path[-1]:
        raise TransferError('Hamilton endpoint differs from the accepted route.')
    forward=records['forward_speed137_trial.json']['final_robot']
    return dict(parent_sha256=candidate['parent']['parent_sha256'],
        accepted_candidate_sha256=HASHES['candidate.json'],evidence_hashes=deepcopy(HASHES),
        endpoint_reference=deepcopy(config),
        measured_return_start=dict(pose=forward['pose_mm'],joints=forward['joints']),
        forward=deepcopy(path),reverse=deepcopy(candidate['routes']['reverse']),
        envelope=env,old_home_area=candidate['parent']['old_home_area'],
        physical_clearance_verified=True,current_clearance_verified=False,
        operator_accepted_both_directions=True)
