"""Read-only IK review: raise the tested Squid transit corridor by 5 mm."""
import json,hashlib,time
from copy import deepcopy
from proof_lift_plate import api,ROOT
from autonomy import check_path

FOLDER=ROOT/'operator_ui/reports/projected_alignment'
OUTPUT=FOLDER/'squid_higher_retreat_20261027_queue_candidate.json'

def main():
    source=FOLDER/'squid_48well_clearance_20261027_candidate.json'
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!='bcc7e59c5de810a6c8a87643c386e2a980a12889f93d559fd6cd23b4884fc6c2':
        raise RuntimeError('Source route changed.')
    prior=json.loads(raw);forward=deepcopy(prior['routes']['forward'])
    for point in forward[1:-1]:point['Z']+=5.0
    state=api('state');r=state['robot'];cfg=api('robot_params')
    if not r.get('connected') or r.get('errors') or state['sequence']['active']:raise RuntimeError('Fresh healthy idle feedback required.')
    start={k:r['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    if cfg!=prior['cfg'] or {k:list(v) for k,v in env.items()}!=prior['envelope']:raise RuntimeError('Limits changed.')
    recovery=[start,{**{k:round(v,2) for k,v in start.items()},'Z':291.24},forward[2],forward[1],forward[0]]
    q=r['joints'];offset=q['J1']-start['Z'];checks=[]
    for label,path in [('recovery_return',recovery),('forward',forward),('reverse',list(reversed(forward)))]:
        for a,b in zip(path,path[1:]):
            q=check_path(a,b,q,cfg,env);q['J1']=b['Z']+offset
            if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise RuntimeError('J1/J3 limit.')
            checks.append(dict(route=label,target=b,joints=deepcopy(q)))
    record=dict(status='offline_checked_pending_contact_inspection',at=time.time(),
        parent_candidate_sha256=hashlib.sha256(raw).hexdigest(),cfg=cfg,envelope=prior['envelope'],
        routes=dict(recovery_return=recovery,forward=forward,reverse=list(reversed(forward))),
        validation=checks,live_robot=r,transit_speed=137,descent_speed=5,initial_lift_mm=5,initial_lift_speed=5,
        reason='Operator confirmed caught claw and requested 5 mm higher clearance; vertical recovery completed. Same XY/yaw corridor and accepted Z270 seating, all transit heights raised from286.24 to291.24.',
        hardware_commands_sent=False,physical_clearance_verified=False)
    with OUTPUT.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    print(json.dumps(dict(candidate=str(OUTPUT),sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),routes=record['routes'],ik_passed=True)))

if __name__=='__main__':main()
