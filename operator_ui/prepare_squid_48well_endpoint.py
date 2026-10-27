"""Prepare exact revised Squid route from the operator's saved endpoint. No motion."""
import json,math,time
from copy import deepcopy
from scope_compact137 import accepted
from projected_pickup import ROOT,sha
from autonomy import check_path,wrap
from pick_and_hold.Calibration.fast_disk import ik
from proof_lift_plate import write

FOLDER=ROOT/'operator_ui/reports/projected_alignment'
SOURCE=FOLDER/'squid_48well_taught_endpoint_20261027T1145.json'
OUTPUT=FOLDER/'squid_48well_endpoint_candidate_20261027T1145.json'

def main():
    taught=json.loads(SOURCE.read_bytes());parent,forward,hashes,trials=accepted()
    target={k:math.floor(taught['endpoint'][k]*100+.5)/100 for k in ('X','Y','Z','Rz')}
    route=deepcopy(forward)
    route[-2]={**target,'Z':forward[-2]['Z']};route[-1]=target
    raw_cfg=json.loads((ROOT/'operator_ui/robot_params.json').read_bytes())
    cfg={k:v for k,v in raw_cfg.items() if isinstance(v,(float,int))}
    if cfg!=parent['params']:raise RuntimeError('Reviewed joint configuration changed.')
    env={k:tuple(v) for k,v in parent['envelope'].items()}
    home_joints=trials['reverse']['final_robot']['joints']
    reference=(taught['joints']['J2'],taught['joints']['J3'])
    endpoint_joints=ik(target['X'],target['Y'],reference,cfg)
    bound=abs(cfg['j2_min_deg'])-cfg['j2_margin_deg']
    if abs(endpoint_joints[0])>bound:
        # Offline alternatives only; no target replacement or limit relaxation.
        alternatives=[]
        for mode in ('nearest_xy','x_only'):
            found=None
            for i in range(1,201):
                distance=i*.05
                angles=range(360) if mode=='nearest_xy' else [0]
                for angle in angles:
                    rad=math.radians(angle)
                    candidate={**target,'X':round(target['X']+distance*math.cos(rad),2),
                               'Y':round(target['Y']+distance*math.sin(rad),2)}
                    try:
                        a,b=ik(candidate['X'],candidate['Y'],reference,cfg)
                        if abs(a)>bound-.1:continue
                        proposed=deepcopy(route);proposed[-2]={**candidate,'Z':route[-2]['Z']};proposed[-1]=candidate
                        q=dict(home_joints)
                        for start,end in zip(proposed,proposed[1:]):q=check_path(start,end,q,cfg,env)
                        reverse_q=dict(q);reverse_q['J1']=candidate['Z']+(home_joints['J1']-route[0]['Z'])
                        for start,end in zip(list(reversed(proposed)),list(reversed(proposed))[1:]):
                            reverse_q=check_path(start,end,reverse_q,cfg,env)
                        found=dict(kind=mode,endpoint=candidate,displacement_mm=math.hypot(candidate['X']-target['X'],candidate['Y']-target['Y']),
                                   predicted_j2_deg=a,routes=dict(forward=proposed,reverse=list(reversed(proposed))),
                                   geometry_only=True,clearance_and_seating_verified=False)
                        break
                    except Exception:continue
                if found:break
            alternatives.append(found)
        record=dict(at=time.time(),status='blocked_by_existing_j2_limit',source=SOURCE.relative_to(ROOT).as_posix(),
            source_sha256=sha(SOURCE.read_bytes()),requested_route=route,cfg=cfg,envelope=parent['envelope'],
            endpoint_j2_deg=endpoint_joints[0],j2_automatic_bound_deg=bound,alternatives=alternatives,
            hardware_commands_sent=False,limits_changed=False,physical_trial_started=False)
        if OUTPUT.exists():raise RuntimeError('Candidate already exists; preserve it.')
        write(OUTPUT,record)
        print(json.dumps(record));return
    validation={}
    for name,path,joints in [('forward',route,home_joints),('reverse',list(reversed(route)),taught['joints'])]:
        q=dict(joints);offset=q['J1']-path[0]['Z'];checked=[]
        for start,end in zip(path,path[1:]):
            q=check_path(start,end,q,cfg,env)
            q['J1']=end['Z']+offset
            if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise RuntimeError('J1/J3 outside travel limits.')
            checked.append(dict(pose=end,joints=dict(q)))
        expected=taught['joints'] if name=='forward' else home_joints
        if any(abs(q[k]-expected[k])>.5 for k in ('J1','J2','J3','J4')):raise RuntimeError('Arrival winding differs from teaching.')
        validation[name]=dict(start_joints=joints,checked=checked)
    record=dict(at=time.time(),status='offline_checked_pending_supervised_trial',
        source=SOURCE.relative_to(ROOT).as_posix(),source_sha256=sha(SOURCE.read_bytes()),
        parent_hashes=hashes,parent_route=forward,routes=dict(forward=route,reverse=list(reversed(route))),
        cfg=cfg,envelope=parent['envelope'],validation=validation,
        transit_speed=137,descent_speed=10,gripper_commands=False,
        note='Preserve Home lift and X354/Y270 transit. Move the overhead approach to the taught endpoint XY/yaw; descend vertically. No release or pickup authorized by this candidate.',
        physical_clearance_verified=False,seating_verified=False)
    if OUTPUT.exists():raise RuntimeError('Candidate already exists; preserve it.')
    write(OUTPUT,record)
    print(json.dumps(dict(path=str(OUTPUT),sha256=sha(OUTPUT.read_bytes()),route=route,validation='IK, joint winding and existing workspace passed both ways')))

if __name__=='__main__':main()
