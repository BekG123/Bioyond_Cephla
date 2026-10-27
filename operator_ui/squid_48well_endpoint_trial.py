"""One supervised trial of the approved nearby 48-well Squid endpoint.

Preserves historical Squid routes. No release, startup, reset, or automatic retry.
"""
from copy import deepcopy
import hashlib,json,math,time
from projected_pickup import ROOT,load,accepted_grip
from autonomy import check_path,TransferError
from scope_step_trial import near,preflight
from scope_compact137 import accepted,HoldingService

SOURCE=ROOT/'operator_ui/reports/projected_alignment/squid_48well_clearance_20261027_candidate.json'
SHA='bcc7e59c5de810a6c8a87643c386e2a980a12889f93d559fd6cd23b4884fc6c2'
# New supervised trial after operator removed the obstructing Squid component.
# Preserve the previous completed checkpoint receipt and the same checked route.
OUTPUT=SOURCE.with_name('squid_48well_obstruction_removed_20261027_trial.json')

def reference():
    raw=SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise TransferError('Squid candidate changed.')
    plan=json.loads(raw)
    parent,old,_,_=accepted()
    path=plan['routes']['forward']
    if (plan['status']!='offline_checked_pending_supervised_trial' or path[:3]!=old[:3]
            or path[-1]!=dict(X=216.10,Y=374.52,Z=270.0,Rz=85.69)
            or path[-2]!={**path[-1],'Z':286.24}
            or plan['cfg']!=parent['params'] or plan['envelope']!=parent['envelope']):
        raise TransferError('Exact approved endpoint/parent route required.')
    return plan,path

def validate_route(start,points,phase=None):
    if isinstance(phase,str) and phase.startswith('raised_'):
        from squid_48well_higher_route import validate_route as raised_route
        return raised_route(start,points,phase)
    plan,path=reference()
    phases={None:(path[0],path[1:]),'transit':(path[0],path[1:-1]),'descent':(path[-2],path[-1:])}
    lifted={**path[-1], 'Z':path[-1]['Z']+5.0}
    phases['departure']=(path[-1],[lifted])
    phases['return']=(lifted,list(reversed(path[:-1])))
    if phase not in phases:raise TransferError('Unknown Squid trial phase.')
    origin,targets=phases[phase]
    if points!=targets:raise TransferError('Only the exact approved nearby Squid targets are allowed.')
    near(start,origin,.05)
    return plan

def check_route(start,points,joints,cfg,envelope,phase=None):
    plan=validate_route(start,points,phase)
    if cfg!=plan['cfg'] or {k:list(v) for k,v in envelope.items()}!=plan['envelope']:
        raise TransferError('Squid trial limits changed.')
    previous=start;q=deepcopy(joints);offset=q['J1']-start['Z']
    for point in points:
        q=check_path(previous,point,q,cfg,envelope)
        q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Squid trial J1/J3 limit.')
        previous=point
    return q

def review(service,cfg):
    if OUTPUT.exists():raise TransferError('This Squid trial was already attempted; inspect before retrying.')
    state=preflight(service);plan,path=reference()
    near(state['pose_mm'],path[0],.05)
    check_route(path[0],path[1:],state['joints'],cfg,service.envelope)
    profile,digest=load()
    if not accepted_grip(profile):raise TransferError('Accepted 48-well grip reference required.')
    e1=state.get('external_axes',{}).get('E1')
    if type(e1) not in (float,int) or not math.isfinite(e1) or not 3.85<=e1<=3.95:
        raise TransferError('Expected accepted 48-well grip near 3.9 mm.')
    from trajectory_queue import LuaTrajectory,travel_program_blocker
    blocker=travel_program_blocker(LuaTrajectory(service).capability(),137)
    if blocker:raise TransferError(blocker)
    return dict(candidate_sha256=SHA,profile_sha256=digest,start=path[0],points=path[1:],
        joints=state['joints'],e1=e1,envelope=plan['envelope'],transit_speed=137,descent_speed=5)

def execute(run,service,cfg,approved):
    fresh=review(service,cfg)
    if any(fresh[k]!=approved[k] for k in ('candidate_sha256','profile_sha256','start','points','envelope')):
        raise TransferError('Squid trial changed before execution.')
    if abs(fresh['e1']-approved['e1'])>.05 or any(abs(fresh['joints'][k]-approved['joints'][k])>.5 for k in fresh['joints']):
        raise TransferError('Start feedback changed.')
    record=dict(status='started',started_at=time.time(),plan=fresh,samples=[],phases=[],
        authorization='Operator removed the interfering Squid component and requested full retry; confirmed plate in calibration holder, empty jaws, clear route, hands clear and E-stop supervised. Stop at Z270 for seating inspection.',
        gripper_commands=False,program_restart=False,seating_accepted=False,release_executed=False)
    with OUTPUT.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def save():OUTPUT.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    holding=HoldingService(service,fresh['e1'],fresh['envelope'])
    from trajectory_queue import LuaTrajectory
    _,path=reference()
    try:
        for phase,start,points,speed in [('transit',path[0],path[1:-1],137),('descent',path[-2],path[-1:],5)]:
            if run.stopped():raise TransferError('Stopped before Squid '+phase)
            state=preflight(holding);near(state['pose_mm'],start,.05)
            run.say(f'48-well Squid {phase} at {speed}; stop before release.')
            def progress(stage,done,total):
                record['samples'].append(dict(at=time.time(),phase=phase,stage=stage,done=done,total=total,robot=service.status()))
                save()
            result=LuaTrajectory(holding).execute(run,start,state['joints'],points,cfg,speed,progress,
                reviewed=True,scope_trial=True,scope_speed137=True,scope_phase=phase)
            if not result.get('ok'):raise TransferError('Squid trial phase completion uncertain.')
            record['phases'].append(dict(phase=phase,speed=speed,result=result));save()
        state=preflight(holding);near(state['pose_mm'],path[-1],.1)
        record['status']='motion_completed_awaiting_seating_inspection'
        return dict(ok=True,record=str(OUTPUT),pose=state['pose_mm'],seating_inspection_required=True,clearance_checkpoint=True,release_executed=False)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop_response']=service.program('stop')
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record.update(finished_at=time.time(),final_robot=service.status());save()
