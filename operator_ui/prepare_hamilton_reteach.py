"""Offline endpoint-only Hamilton proposal from an already saved status snapshot.

No network, controller calls, runtime configuration changes or motion permission.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from autonomy import check_path, TransferError
from hamilton_true_home import configured, segment_envelope, ROOT
from scope_compact137 import accepted

KEYS=('X','Y','Z','Rz')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    args=parser.parse_args()
    raw=args.snapshot.read_bytes()
    state=json.loads(raw.decode('utf-8-sig'));robot=state['robot']
    if not robot.get('ok') or robot.get('errors') or state['sequence']['active']:
        raise ValueError('Snapshot must show healthy feedback and no active sequence.')
    measured={k:robot['pose_mm'][k] for k in KEYS}
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in measured.values()):
        raise ValueError('Invalid measured pose.')
    endpoint={k:math.floor(v*100+.5)/100 for k,v in measured.items()}
    parent=configured();forward=deepcopy(parent['forward']);forward[-1]=endpoint
    cfg=json.loads((ROOT/'robot_params.json').read_text(encoding='utf-8-sig'))
    _,_,_,trials=accepted()
    routes={'forward':forward,'reverse':list(reversed(forward))}
    seeds={'forward':trials['reverse']['final_robot']['joints'],
           'reverse':robot['joints']}
    offset=robot['joints']['J1']-measured['Z']
    validation={}
    for direction,path in routes.items():
        q=deepcopy(seeds[direction]);q['J1']=path[0]['Z']+offset
        checked=[];box_failures=[]
        for index,(a,b) in enumerate(zip(path,path[1:])):
            changed=(direction=='forward' and index==2) or (direction=='reverse' and index==0)
            # Explicitly report the new segment's box violation. Kinematic
            # assessment outside the box is offline only, never authorization.
            try:
                check_path(a,b,q,cfg,parent['envelope'])
            except TransferError as error:
                box_failures.append(dict(segment=index+1,reason=str(error)))
            env=None if changed else segment_envelope(a,b,parent['envelope'],parent)
            q=check_path(a,b,q,cfg,env)
            q['J1']=b['Z']+offset
            if not 0<=q['J1']<=400 or abs(q['J3'])>180:
                raise TransferError('Vertical or planar joint travel exceeded.')
            checked.append(dict(pose=b,joints=deepcopy(q),changed_segment=changed))
        validation[direction]=dict(ik_continuity_and_joint_limits_passed=True,
            checked=checked,ordinary_workspace_passed=not box_failures,
            ordinary_workspace_refusals=box_failures,
            length_mm=sum(math.dist([a[k] for k in KEYS[:3]],
                                    [b[k] for k in KEYS[:3]]) for a,b in zip(path,path[1:])))
    predicted=validation['forward']['checked'][-1]['joints']
    joint_error={k:predicted[k]-robot['joints'][k] for k in ('J1','J2','J3','J4')}
    if max(abs(v) for v in joint_error.values())>.5:
        raise TransferError('Proposed arrival differs from the taught joint configuration.')
    old=parent['forward'][-1];hover=forward[-2]
    record=dict(schema='cephla.hamilton-endpoint-proposal.v1',
        created_at=datetime.now(timezone.utc).isoformat(),
        status='offline_proposal_not_active',snapshot=str(args.snapshot),
        snapshot_sha256=hashlib.sha256(raw).hexdigest(),snapshot_ts=state['ts'],
        operator_feedback='Hamilton was moved up. Save the current arm coordinate and keep the same path with this final destination.',
        measured_pose=measured,measured_joints=robot['joints'],measured_e1_mm=robot['external_axes']['E1'],
        payload='unknown; E1 feedback does not establish plate presence',
        endpoint=endpoint,endpoint_delta={k:measured[k]-old[k] for k in KEYS},
        parent=parent,parent_sha256=hashlib.sha256(json.dumps(parent,sort_keys=True).encode()).hexdigest(),
        source_hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                      for name in ('hamilton_endpoint.json','points.json','robot_params.json','envelope.json')},
        routes=routes,cfg=cfg,validation=validation,arrival_joint_error=joint_error,
        preserved_waypoints=forward[:-1],queued_targets=3,speed=137,zone=-1,
        final_segment_horizontal_mm=math.hypot(endpoint['X']-hover['X'],endpoint['Y']-hover['Y']),
        physical_clearance_verified=False,hardware_execution=False,runtime_promoted=False,
        limitation='Endpoint-only replacement makes the final descent diagonal. New Hamilton geometry has not been surveyed. '
                   'Existing runtime pins the old XY/yaw and must not execute this proposal. '
                   'No workspace limits or route exceptions were changed.')
    output=args.snapshot.with_name('candidate.json')
    with output.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(report=str(output),pose=measured,delta=record['endpoint_delta'],
        forward=forward,final_segment_horizontal_mm=record['final_segment_horizontal_mm'],
        both_directions_ik_passed=True,arrival_joint_error=joint_error,
        runtime_promoted=False),indent=2))


if __name__=='__main__':main()
