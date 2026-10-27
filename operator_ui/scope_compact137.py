"""One requested scope/Home/scope trial, exact accepted geometry, Lua speed 137."""
import hashlib
import json
import math
import time
from autonomy import TransferError, check_path
from scope_compact_trial import PLAN, ROOT
from scope_step_trial import near, preflight
from trajectory_queue import LuaTrajectory, prepare_points

OUTPUT=PLAN.with_name('compact4_roundtrip_speed137_trial.json')
DESCENT_SPEED = 10
TRANSIT_SPEED = 137


def speed_policy():
    return dict(version=1, transit_mm_s=TRANSIT_SPEED, final_descent_mm_s=DESCENT_SPEED,
                return_mm_s=TRANSIT_SPEED, stop_before_final_descent=True)


def accepted():
    raw=PLAN.read_bytes();plan=json.loads(raw)
    forward=[plan['start']]+plan['points']
    if len(forward)!=5:raise TransferError('Four-point scope route required.')
    hashes={'candidate':hashlib.sha256(raw).hexdigest()};trials={}
    for name,path in [('forward',forward),('reverse',list(reversed(forward)))]:
        source=PLAN.with_name(f'compact4_{name}_speed40_trial.json')
        data=source.read_bytes();trial=json.loads(data)
        if trial['status']!='completed' or len(trial['steps'])!=4 or any(s.get('status')!='arrived' for s in trial['steps']):
            raise TransferError('Completed speed-40 baseline required in both directions.')
        if trial['plan']['plan_sha256']!=hashes['candidate'] or trial['plan']['points']!=path[1:]:
            raise TransferError('Baseline geometry changed.')
        near(trial['plan']['start'],path[0],.001)
        if trial['plan']['cfg']!=plan['params'] or trial['plan']['envelope']!=plan['envelope']:
            raise TransferError('Baseline policy changed.')
        hashes[name]=hashlib.sha256(data).hexdigest();trials[name]=trial
    hfile=json.loads((ROOT/'operator_ui/points.json').read_text(encoding='utf-8-sig'))
    h=hfile['points'][hfile['roles']['home']]
    near(forward[0],dict(X=h['x'],Y=h['y'],Z=h['z_grip'],Rz=h['rz']),.001)
    return plan,forward,hashes,trials


def pickup_departure_start(start, forward):
    """Recognize only the tested 0–5 mm vertical pickup above Squid.

    This shortens the first reverse leg; none of its target points change.
    Joint winding, IK, workspace and gripper checks still apply separately.
    """
    seated, overhead = forward[-1], forward[-2]
    try:
        near({**start, 'Z': seated['Z']}, seated, .05)
        near({**overhead, 'Z': seated['Z']}, seated, .05)
        return seated['Z'] <= start['Z'] <= min(seated['Z'] + 5.05, overhead['Z'])
    except (TransferError, KeyError):
        return False


def validate_route(start,points,phase=None):
    _,forward,_,_=accepted()
    if phase is not None:
        phases={'transit':(forward[0],forward[1:-1]),
                'descent':(forward[-2],[forward[-1]])}
        if phase not in phases:
            raise TransferError('Unknown scope travel phase.')
        origin,targets=phases[phase]
        if points!=targets:
            raise TransferError('Scope phase must preserve its exact tested targets.')
        near(start,origin,.05)
        return
    for path in (forward,list(reversed(forward))):
        if points==path[1:]:
            if path[0] == forward[-1] and pickup_departure_start(start, forward):
                return
            near(start,path[0],.05)
            return
    raise TransferError('Scope queue must preserve the exact four tested targets.')


def execute_route(run, service, start, joints, points, cfg, progress):
    """Production speed policy; historical speed-137 trials stay immutable."""
    validate_route(start,points)
    _,forward,_,_=accepted()
    if points != forward[1:]:
        return LuaTrajectory(service).execute(run,start,joints,points,cfg,TRANSIT_SPEED,progress,
            reviewed=True,scope_compact=True,scope_speed137=True)
    phases=[]
    for phase,origin,targets,speed in (
        ('transit',start,points[:-1],TRANSIT_SPEED),
        ('descent',forward[-2],points[-1:],DESCENT_SPEED)):
        if run.stopped():
            raise TransferError('Stopped before Squid '+phase+'.')
        preflight(service)
        near(service.pose_mm(),origin,.05)
        run.say('Squid '+phase+f' at {speed} mm/s.')
        run.audit('squid_speed_phase',phase=phase,speed_mm_s=speed,start=origin,points=targets)
        result=LuaTrajectory(service).execute(run,origin,service.joints(),targets,cfg,speed,
            lambda stage,done,total:progress(phase+':'+stage,done,total),
            reviewed=True,scope_compact=True,scope_speed137=True,scope_phase=phase)
        if not result.get('ok'):
            raise TransferError('Squid '+phase+' did not confirm completion.')
        phases.append(dict(phase=phase,speed_mm_s=speed,result=result))
    return dict(ok=True,executor='lua_queue',points=len(points),endpoint=points[-1],
                speed_policy=speed_policy(),phases=phases)


class HoldingService:
    def __init__(self,service,e1,envelope):self.service,self.e1,self.envelope_ref=service,e1,envelope
    def __getattr__(self,key):return getattr(self.service,key)
    def _preflight(self):
        refusal=self.service._preflight()
        if refusal:return refusal
        if not self.service.envelope_enabled or any(list(self.service.envelope[k])!=self.envelope_ref[k] for k in ('X','Y','Z')):
            return 'Scope workspace changed.'
        value=self.service.external_axes().get('E1')
        if type(value) not in (float,int) or not math.isfinite(value) or abs(value-self.e1)>.1:
            return 'Gripper feedback changed; inspect before continuing.'
        return None


def review(service,cfg):
    if OUTPUT.exists():raise TransferError('Speed-137 scope trial already attempted; review before another attempt.')
    plan,forward,hashes,trials=accepted()
    if cfg!=plan['params'] or any(list(service.envelope[k])!=plan['envelope'][k] for k in ('X','Y','Z')):
        raise TransferError('Reviewed scope policy changed.')
    state=preflight(service);near(state['pose_mm'],forward[-1],.05)
    expected=trials['forward']['final_robot']['joints']
    if any(abs(state['joints'][k]-expected[k])>.5 for k in ('J1','J2','J3','J4')):
        raise TransferError('Scope starting joint winding changed.')
    capability=LuaTrajectory(service).capability()
    if not capability.get('available') or capability.get('max_speed_mm_s',0)<137:
        raise TransferError('Running speed-137 Lua program required; no automatic restart.')
    e1=service.external_axes().get('E1')
    if type(e1) not in (float,int) or not math.isfinite(e1):raise TransferError('Missing gripper feedback.')
    paths=[list(reversed(forward)),forward];q=state['joints'];j1offset=q['J1']-state['pose_mm']['Z']
    for path in paths:
        prepare_points(path[0],q,path[1:],cfg,reviewed=True,scope_compact=True)
        previous=path[0]
        for point in path[1:]:
            q=check_path(previous,point,q,cfg,service.envelope)
            if not 0<=point['Z']+j1offset<=400 or abs(q['J3'])>180:raise TransferError('J1/J3 limit')
            previous=point
    return dict(sources=hashes,paths=paths,cfg=cfg,envelope=plan['envelope'],e1_start=e1,speed=137)


def execute(run,service,cfg,approved):
    current=review(service,cfg)
    if {k:v for k,v in current.items() if k!='e1_start'}!={k:v for k,v in approved.items() if k!='e1_start'} or abs(current['e1_start']-approved['e1_start'])>.05:
        raise TransferError('Scope trial changed before dispatch.')
    record=dict(status='started',started_at=time.time(),plan=approved,directions=[],
        authorization='Operator accepted compact route and requested scope to Home then Home to scope at speed 137, with existing corridor clearance and E-stop supervision.',
        gripper_commands=False,program_restart=False,operator_acceptance=None)
    with OUTPUT.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def save():OUTPUT.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    holding=HoldingService(service,approved['e1_start'],approved['envelope'])
    try:
        for label,path in zip(('Scope to Home','Home to scope'),approved['paths']):
            if run.stopped():raise TransferError('Stopped before next scope leg.')
            preflight(holding);near(service.pose_mm(),path[0],.05)
            if accepted()[2]!=approved['sources']:raise TransferError('Source trial changed.')
            phase=dict(name=label,started_at=time.time(),start_robot=service.status(),samples=[])
            record['directions'].append(phase);save()
            run.say(label+' — four queued points at speed 137.')
            def progress(stage,done,total):
                sample=dict(t=time.time(),stage=stage,done=done,total=total,pose_mm=service.pose_mm(),joints=service.joints(),e1=service.external_axes().get('E1'))
                phase['samples'].append(sample);save()
                run.audit('scope_compact137_progress',direction=label,**sample)
            result=LuaTrajectory(holding).execute(run,path[0],service.joints(),path[1:],cfg,137,progress,
                reviewed=True,scope_compact=True,scope_speed137=True)
            if not result.get('ok'):raise TransferError('Scope queue did not confirm completion.')
            preflight(holding);near(service.pose_mm(),path[-1],.2)
            phase.update(status='completed',finished_at=time.time(),result=result,final_robot=service.status());save()
            run.say(label+' completed.','good')
        record.update(status='completed',final_robot=service.status())
        return dict(ok=True,record=str(OUTPUT),speed=137,pose_mm=service.pose_mm(),directions=[dict(name=p['name'],seconds=p['finished_at']-p['started_at']) for p in record['directions']])
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        # Queue stops faults internally; also cover faults between legs.
        try:record['stop_result']=service.program('stop')
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();save();run.audit('scope_compact137_trial',record=str(OUTPUT),status=record['status'])
