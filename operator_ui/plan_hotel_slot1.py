"""Offline hotel-slot candidates from the recorded demonstration; no robot API."""
import hashlib
import json
import math
from pathlib import Path
from plan_short_side_hamilton import validate

ROOT=Path(__file__).resolve().parents[1]
SESSION=ROOT/'operator_ui/reports/plate_session/hotel_slot_teaching_20261111_212833'
KEYS=('X','Y','Z','Rz')


def build():
    raw=(SESSION/'samples.jsonl').read_bytes();rows=[json.loads(x) for x in raw.splitlines()]
    endpoint=SESSION/'slot_1_loading_pose.json';taught=json.loads(endpoint.read_bytes())
    r=rows[0]['robot'];start={k:r['pose_mm'][k] for k in KEYS};end={k:taught['pose_mm'][k] for k in KEYS}
    settings=json.loads((ROOT/'operator_ui/robot_params.json').read_text(encoding='utf-8-sig'))
    cfg={k:v for k,v in settings.items() if type(v) in (int,float)}
    env=dict(X=(200,450),Y=(-250,380),Z=(70,400))
    # Adjust the demonstrated X235/Y42 pivot inward to satisfy the existing
    # J2 planning limit. Do not reproduce the observed X156..199 excursion.
    turn=dict(X=240.,Y=25.,Z=start['Z'],Rz=end['Rz'])
    high=dict(turn,Z=250.44)
    entry=dict(X=266.69,Y=-133.34,Z=end['Z'],Rz=end['Rz'])
    candidates={}
    for name,points in [('compact_three',[high,entry,end]),
                        ('phased_five',[turn,high,dict(entry,Z=250.44),entry,end])]:
        forward=validate(start,points,r['joints'],cfg,env,taught['joints'])
        reverse_points=list(reversed([start]+points))[1:]
        reverse=validate(end,reverse_points,forward['endpoint_joints'],cfg,env,r['joints'])
        if not forward['workspace_valid'] or not reverse['workspace_valid']:raise ValueError('Candidate violates unchanged workspace.')
        candidates[name]=dict(points=points,validation=forward,reverse_points=reverse_points,reverse_validation=reverse,
            queues_per_direction=1,travel_speed_requested=137,final_insertion_speed_candidate=5,
            blending='Transit corners only, subject to swept-clearance review; preserve straight final insertion and exact stop.',
            physical_clearance_verified=False,execution_enabled=False)
    observations=[x['robot']['pose_mm'] for x in rows if x.get('valid')]
    return dict(status='offline_candidates_not_executable',motion_sent=False,slot=1,
        source=str(SESSION/'samples.jsonl'),source_sha256=hashlib.sha256(raw).hexdigest(),
        endpoint_source=str(endpoint),endpoint_sha256=hashlib.sha256(endpoint.read_bytes()).hexdigest(),
        operator_endpoint_semantics='User confirmed this is the slot1 release/pickup position.',
        photograph='C:/Users/Cephla/Downloads/IMG_6438.jpeg',
        start=start,start_joints=r['joints'],endpoint=end,config=cfg,envelope=env,
        recorded_bounds={k:[min(x[k] for x in observations),max(x[k] for x in observations)] for k in KEYS},
        adjusted_pivot_reason='Recorded low turn X235/Y42 crosses J2 planning limit; candidate uses X240/Y25. New sweep needs review.',
        final_insertion_length_mm=math.dist([entry[k] for k in KEYS[:3]],[end[k] for k in KEYS[:3]]),
        candidates=candidates,limitations=[
            'Starts at recorded HOME clearance, not the seated pickup pose. Grip, proof lift and connection must be planned separately.',
            'Empty-jaw demonstration does not establish clearance of a loaded plate.',
            'No calibrated rack collision geometry; photograph alone cannot verify swept volume.',
            'Three-point option combines rise/turn and crossing/lowering, departing from taught phase order.',
            'Five-point option preserves phase order but adjusts the turning/lifting corridor to remain within limits.',
            'No other slot inferred and no release/grip settings for this slot have been validated.'])


if __name__=='__main__':
    d=build();out=SESSION/'slot_1_route_candidates_v1.json'
    with out.open('x',encoding='utf-8') as f:json.dump(d,f,indent=2)
    print(json.dumps(dict(record=str(out),insertion_mm=d['final_insertion_length_mm'],
        candidates={k:dict(points=v['points'],length_mm=v['validation']['length_mm'],
            ik_and_workspace_valid=True) for k,v in d['candidates'].items()}),indent=2))
