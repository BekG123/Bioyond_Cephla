"""Offline candidate: fast wrist turn above HOME, then direct Hamilton entry.

Preserves the accepted route. IK validation does not establish rack clearance.
"""
import argparse,hashlib,json,time
from copy import deepcopy
from pathlib import Path
from cellvis24_rack_route import reference,PLAN,PLAN_SHA
from plan_short_side_hamilton import validate

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'operator_ui/reports/plate_session/cellvis24_validation/hamilton_direct_fast_wrist_candidate_v3.json'
ACCEPTED=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/105936a6411a46a49fc7db88e1107cd4/operator_acceptance.json'

def build():
    p=reference();f=p['routes']['forward'];start=f['start'];old=f['points']
    accepted=json.loads(ACCEPTED.read_bytes())
    if not accepted.get('plate_secure') or accepted['route_sha256']!=PLAN_SHA:
        raise ValueError('Accepted successful baseline required.')
    above=dict(start,Z=old[0]['Z'])
    mid=dict(above,Rz=old[1]['Rz']);turned=dict(above,Rz=old[2]['Rz'])
    points=[above,mid,turned]+deepcopy(old[-3:])
    kinds=['L','J','J','L','L','L'];speeds=[137]*5+[5]
    v=validate(start,points,f['start_joints'],p['config'],p['station_envelope'],f['validation']['endpoint_joints'])
    back=list(reversed([start]+points))[1:];back_kinds=list(reversed(kinds));back_speeds=list(reversed(speeds))
    rv=validate(points[-1],back,v['endpoint_joints'],p['config'],p['station_envelope'],f['start_joints'])
    if not v['workspace_valid'] or not rv['workspace_valid']:raise ValueError('Candidate exceeds station envelope.')
    # Joint moves are only pure wrist changes: same XYZ and same J1/J2/J3
    # on the continuous IK branch, hence no joint-space translation shortcut.
    for rstart,ps,ks,val in [(start,points,kinds,v),(points[-1],back,back_kinds,rv)]:
        prev=rstart
        for index,(point,kind) in enumerate(zip(ps,ks)):
            if kind=='J':
                if any(abs(point[k]-prev[k])>.001 for k in ('X','Y','Z')):raise ValueError('Joint turn translates.')
                group=[s['joints'] for s in val['dense_samples'] if s['segment']==index]
                if any(max(q[k] for q in group)-min(q[k] for q in group)>.001 for k in ('J1','J2','J3')):
                    raise ValueError('Joint turn changes arm configuration.')
            prev=point
    result=dict(status='offline_candidate_pending_clearance_and_publish',at=time.time(),motion_sent=False,execution_enabled=False,
        parent_path=str(PLAN.relative_to(ROOT)),parent_sha256=PLAN_SHA,
        accepted_baseline=str(ACCEPTED.relative_to(ROOT)),acceptance_sha256=hashlib.sha256(ACCEPTED.read_bytes()).hexdigest(),
        config=p['config'],global_envelope=p['global_envelope'],station_envelope=p['station_envelope'],
        proposed_pivot=above,clearance_verified=False,required_optional_capability=220111,
        routes=dict(forward=dict(start=start,start_joints=f['start_joints'],points=points,kinds=kinds,segment_speeds=speeds,validation=v),
                    reverse=dict(start=points[-1],start_joints=v['endpoint_joints'],points=back,kinds=back_kinds,segment_speeds=back_speeds,validation=rv)),
        comparison=dict(baseline_xyz_mm=f['validation']['length_mm'],candidate_xyz_mm=v['length_mm'],
            baseline_points=len(old),candidate_points=len(points),baseline_wrist_s=23.697580099105835,
            predicted_time_s=None),
        rationale='Remove X236.19 detour; lift above HOME, turn at fixed XYZ with two queued MoveJ137 segments retaining the taught negative winding, then direct MoveL to site4 entry Z77. One final completion barrier per direction.',
        limitations=['New wrist/plate sweep above HOME and direct diagonal entry require physical clearance review.',
            'MoveJ137 is a controller speed setting, not a guaranteed137 degrees/s. Runtime improvement needs a measured trial.',
            'Existing successful live route remains selected; no automatic activation.'])
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--save',action='store_true');args=parser.parse_args()
    p=build()
    if args.save:
        with OUTPUT.open('x') as f:json.dump(p,f,indent=2,allow_nan=False)
    print(json.dumps(dict(saved=str(OUTPUT) if args.save else None,comparison=p['comparison'],
        pivot=p['proposed_pivot'],points=p['routes']['forward']['points'],kinds=p['routes']['forward']['kinds'],
        joint_ranges=p['routes']['forward']['validation']['joint_ranges'],execution_enabled=False),indent=2))

if __name__=='__main__':main()
