"""One reviewed loaded pickup/Home round trip, using the commissioned Lua queue."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from autonomy import AlignmentGuard, TransferError, check_path, wrap
from trajectory_queue import LuaTrajectory, prepare_points

ROOT=Path(__file__).resolve().parents[1]
PARENT=ROOT/'operator_ui/reports/pickup_home/20261017T105903Z_plan_loaded_return.json'
OUTPUT=PARENT.with_name('loaded_roundtrip_137_20261017.json')
KEYS=('X','Y','Z','Rz')

def near(actual,expected,tolerance=.05):
    for key in KEYS:
        delta=actual[key]-expected[key]
        if key=='Rz':delta=wrap(delta)
        if abs(delta)>tolerance:raise TransferError('Loaded route start/arrival differs: '+key)

class HoldingService:
    def __init__(self,service):self.service=service
    def __getattr__(self,key):return getattr(self.service,key)
    def _preflight(self):
        refusal=self.service._preflight()
        if refusal:return refusal
        if not self.service.envelope_enabled:return 'Workspace checks must remain enabled.'
        e1=self.service.external_axes().get('E1')
        if type(e1) not in (float,int) or not 3.75<=e1<=3.85:
            return 'Claw position changed during loaded transfer; inspect plate.'
        return None

def stage_path(path,joints,cfg,envelope):
    previous=path[0];stages=[];pending=[];batch_start=previous;batch_joints=joints
    def flush():
        nonlocal pending
        if pending:
            points,_=prepare_points(batch_start,batch_joints,pending,cfg,reviewed=True,home_transit=True)
            stages.append(dict(kind='queue',points=points));pending=[]
    for target in path[1:]:
        rotation=abs(wrap(target['Rz']-previous['Rz']))>.02
        if rotation:
            flush()
            if min(target['Z'],previous['Z'])<299.99 or any(abs(target[k]-previous[k])>.02 for k in ('X','Y','Z')) or abs(wrap(target['Rz']-previous['Rz']))>30.05:
                raise TransferError('Loaded route must rotate in place at clearance height.')
            stages.append(dict(kind='rotate',target=target))
        else:
            if not pending:batch_start,batch_joints=previous,dict(joints)
            pending.append(target)
        joints=check_path(previous,target,joints,cfg,envelope);previous=target
    flush()
    return stages,joints

def review(service,cfg,output=None,repeat_of=None):
    output=Path(output) if output is not None else OUTPUT
    if output.parent.resolve()!=OUTPUT.parent.resolve():raise TransferError('Trial record must stay in the reviewed folder.')
    previous_trial=None
    if repeat_of:
        candidates=set(OUTPUT.parent.glob('loaded_roundtrip_137*.json'))
        if OUTPUT.exists():candidates.add(OUTPUT)
        if not candidates:raise TransferError('No completed loaded trial to replay.')
        latest=max(candidates,key=lambda p:p.stat().st_mtime_ns)
        previous_raw=latest.read_bytes();previous_trial=json.loads(previous_raw)
        if previous_trial.get('status')!='completed' or hashlib.sha256(previous_raw).hexdigest()!=repeat_of:
            raise TransferError('Replay must explicitly reference the latest completed trial; inspect any failed attempt first.')
    raw=PARENT.read_bytes();parent=json.loads(raw)
    if parent.get('status')!='completed_at_home_awaiting_operator_inspection':
        raise TransferError('Completed baseline required.')
    if output.exists():raise TransferError('This speed-137 loaded trial was already attempted; review its result before another run.')
    if output!=OUTPUT and not repeat_of:raise TransferError('Explicit completed-trial reference required for a replay.')
    state=service.status()
    if not state.get('ok') or not state.get('connected') or state.get('errors') or not state.get('enabled') or state['control_mode']['mode']!='auto' or state['program_state']['state']!='running':
        raise TransferError('Already-running Auto required; loaded transfer never starts the program.')
    guarded=HoldingService(service)
    if guarded._preflight():raise TransferError(guarded._preflight())
    support=LuaTrajectory(service).capability()
    if not support.get('available') or support.get('max_speed_mm_s',0)<137:
        raise TransferError('Running speed-137 Lua queue required; do not restart with a held plate.')
    plan=parent['plan']
    if cfg!=plan['config'] or any(list(service.envelope[k])!=plan['envelope'][k] for k in ('X','Y','Z')):
        raise TransferError('Baseline kinematics/workspace changed.')
    if hashlib.sha256((ROOT/'operator_ui/points.json').read_bytes()).hexdigest()!=plan['source_home_sha256']:
        raise TransferError('Saved Home changed since baseline.')
    forward=[plan['start']]+[leg['target'] for leg in parent['commands']]
    forward=[{k:round(p[k],2) for k in KEYS} for p in forward]
    near(state['pose_mm'],forward[-1])
    reverse=list(reversed(forward))
    stages_back,q=stage_path(reverse,state['joints'],cfg,service.envelope)
    stages_home,_=stage_path(forward,q,cfg,service.envelope)
    result=dict(parent_sha256=hashlib.sha256(raw).hexdigest(),home=forward[-1],pickup=forward[0],
        translation_speed=137,wrist_speed=30,config=cfg,
        directions=[dict(name='Home to pickup',stages=stages_back,endpoint=forward[0]),
                    dict(name='Pickup to Home',stages=stages_home,endpoint=forward[-1])])
    if previous_trial and previous_trial['plan']!=result:
        raise TransferError('Replay geometry or configuration differs from the completed trial.')
    return result

def execute(run,service,cfg,approved,output=None,repeat_of=None):
    output=Path(output) if output is not None else OUTPUT
    current=review(service,cfg,output,repeat_of)
    if current!=approved:raise TransferError('Reviewed trial changed before dispatch.')
    record=dict(status='attempt_started',started_at=time.time(),plan=approved,directions=[],
        authorization='Operator requested return to pickup and back to Home at speed 137, preserving held plate.',
        gripper_commands=False,program_restart=False,repeat_of_sha256=repeat_of)
    def save():output.write_text(json.dumps(record,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save()
    holding=HoldingService(service);guard=AlignmentGuard(holding,run,cfg)
    try:
        for direction in approved['directions']:
            phase=dict(name=direction['name'],started_at=time.time(),steps=[])
            record['directions'].append(phase);save()
            run.say(direction['name']+' at translation speed 137; wrist speed 30.')
            for stage in direction['stages']:
                guard._preflight()
                if stage['kind']=='rotate':
                    result=guard.rotate_to_rz(stage['target']['Rz'])
                    near(service.pose_mm(),stage['target'],.1)
                else:
                    pose,q=service.pose_mm(),service.joints()
                    for point in stage['points']:
                        q=check_path(pose,point,q,cfg,service.envelope);pose=point
                    def progress(label,done,total):
                        guard._preflight()
                        run.audit('loaded_home_progress',direction=direction['name'],phase=label,done=done,total=total,
                                  pose_mm=service.pose_mm(),e1=service.external_axes()['E1'])
                    result=LuaTrajectory(holding).execute(run,service.pose_mm(),service.joints(),stage['points'],cfg,137,
                        progress,reviewed=True,home_transit=True,home_speed137=True)
                    if not result.get('ok'):raise TransferError('Loaded queue did not complete.')
                guard._preflight()
                phase['steps'].append(dict(stage=stage,result=result,pose_mm=service.pose_mm(),e1=service.external_axes()['E1']));save()
            near(service.pose_mm(),direction['endpoint'],.1)
            phase.update(finished_at=time.time(),status='completed');save()
            run.say(direction['name']+' completed.','good')
        record.update(status='completed',final_robot=service.status())
        return dict(ok=True,pose_mm=service.pose_mm(),e1=service.external_axes()['E1'],record=str(output))
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        raise
    finally:
        record['finished_at']=time.time();save();run.audit('loaded_home_trial',record=record)
