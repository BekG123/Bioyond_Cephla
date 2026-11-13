"""Offline slot2 estimate from slot1 and operator-provided vertical pitch."""
import json
import hashlib
import time
from pathlib import Path
from plan_hotel_slot1 import SESSION, build
from plan_short_side_hamilton import validate


def build_slot2():
    base=build();pitch=2.5*25.4
    original=base['candidates']['compact_three'];points=[dict(p,Z=p['Z']+pitch) for p in original['points']]
    expected=dict(original['validation']['endpoint_joints']);expected['J1']+=pitch
    forward=validate(base['start'],points,base['start_joints'],base['config'],base['envelope'],expected)
    reverse_points=[points[1],points[0],base['start']]
    reverse=validate(points[-1],reverse_points,forward['endpoint_joints'],base['config'],base['envelope'],base['start_joints'])
    if not forward['workspace_valid'] or not reverse['workspace_valid']:raise ValueError('Slot2 exceeds workspace.')
    source=SESSION/'slot_1_route_candidates_v1.json'
    return dict(status='offline_slot2_candidate_not_executable',motion_sent=False,slot=2,at=time.time(),
        source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),pitch_mm=pitch,
        geometry_assumption='Slot2 has identical X/Y/yaw registration to slot1, 63.5mm higher.',
        start=base['start'],start_joints=base['start_joints'],points=points,forward_speeds=[137,137,5],
        reverse_points=reverse_points,reverse_speeds=[5,137,137],forward_validation=forward,reverse_validation=reverse,
        config=base['config'],envelope=base['envelope'],grip_profile=None,proof_lift_mm=None,
        limitations=['Raised corridor and open/loaded jaw sweep not established by empty slot1 cycles.',
                    'Plate type, gripping sides and rack lift-out clearance need confirmation.',
                    'Reverse is geometric travel only; pickup and lift-out are not yet part of this plan.',
                    'First loaded pickup and slot2 gripping height not physically validated.'])

def build_revised_slot2(crossing_raise_mm=12.7):
    if crossing_raise_mm not in (7.62,12.7):raise ValueError('Only operator-requested crossing offsets are supported.')
    base=build_slot2();old=base['points'];raise_mm=crossing_raise_mm
    points=[dict(old[0],Z=old[0]['Z']+raise_mm),dict(old[1],Z=old[1]['Z']+raise_mm),old[1],old[2]]
    q=base['forward_validation']['endpoint_joints']
    f=validate(base['start'],points,base['start_joints'],base['config'],base['envelope'],q)
    reverse=list(reversed([base['start']]+points))[1:]
    b=validate(points[-1],reverse,f['endpoint_joints'],base['config'],base['envelope'],base['start_joints'])
    if not f['workspace_valid'] or not b['workspace_valid']:raise ValueError('Raised crossing violates workspace.')
    source=SESSION/'slot_2_candidate_v1.json'
    base.update(status='revised_slot2_crossing_not_physically_tested',revision=3 if raise_mm==7.62 else 2,
        previous_candidate_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),crossing_raise_mm=raise_mm,
        operator_change='Raise crossing only; keep pickup height',points=points,forward_speeds=[137,137,5,5],
        reverse_points=reverse,reverse_speeds=[5,5,137,137],forward_validation=f,reverse_validation=b)
    return base


if __name__=='__main__':
    plan=build_slot2();out=SESSION/'slot_2_candidate_v1.json'
    with out.open('x') as f:json.dump(plan,f,indent=2,allow_nan=False)
    print(json.dumps(dict(record=str(out),pitch_mm=plan['pitch_mm'],points=plan['points'],
        forward_and_reverse_ik_valid=True,joint_ranges=plan['forward_validation']['joint_ranges'],motion_sent=False),indent=2))
