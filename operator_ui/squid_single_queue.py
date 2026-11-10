"""Exact accepted November 8 Squid geometry, one mixed-speed Lua transaction."""
from copy import deepcopy
import json
import math
import re
import time
from autonomy import TransferError,check_path,wrap
from scope_step_trial import near,preflight
from scope_compact137 import HoldingService
from squid_handling_route import CURRENT_SOURCE,CURRENT_SHA,load_route
from trajectory_queue import LuaTrajectory,SEGMENT_SPEED_VERSION,KEYS

FOLDER=CURRENT_SOURCE.parent/'single_queue_trials'

def quantize(p):return {k:math.floor(p[k]*100+.5)/100 for k in KEYS}

def route(direction):
    plan=load_route(CURRENT_SOURCE,CURRENT_SHA)
    if direction not in ('forward','reverse'):raise TransferError('Unknown Squid direction')
    path=plan['routes']['from_capture'][:5] if direction=='forward' else plan['routes']['from_capture'][4:]
    return plan,deepcopy(path),([137,137,137,5] if direction=='forward' else [5,137,137,137])

def validate_route(start,points):
    for direction in ('forward','reverse'):
        plan,path,speeds=route(direction)
        try:near(start,path[0],.05)
        except TransferError:continue
        # A strictly vertical departure preserves measured XY/yaw before rounding.
        path[1]={**start,'Z':path[1]['Z']}
        if len(points)==4 and [quantize(p) for p in points]==[quantize(p) for p in path[1:]]:
            return plan,speeds
    raise TransferError('Only the exact accepted November 8 Squid route is allowed')

def check_route(start,points,joints,cfg,envelope):
    plan,_=validate_route(start,points)
    if cfg!=plan['cfg'] or {k:list(v) for k,v in envelope.items()}!=plan['envelope']:
        raise TransferError('Squid queue workspace/settings changed')
    q=deepcopy(joints);offset=q['J1']-start['Z'];previous=start
    for p in points:
        q=check_path(previous,p,q,cfg,envelope);q['J1']=p['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Squid queue J1/J3 limit')
        previous=p
    return q

def check_vertical_feedback(pose,path):
    if pose['Z']<291.24-.15:
        ends=(path[0],path[-1])
        if not any(pose['Z']>=p['Z']-.15 and math.hypot(pose['X']-p['X'],pose['Y']-p['Y'])<=.15 and abs(wrap(pose['Rz']-p['Rz']))<=.15 for p in ends):
            raise TransferError('Squid vertical departure/descent left its checked line')
    if pose['Z']<min(path[0]['Z'],path[-1]['Z'])-.15 or pose['Z']>291.24+.15:
        raise TransferError('Squid vertical motion exceeded reviewed height')

def output_path(trial_id):
    if not isinstance(trial_id,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',trial_id):
        raise TransferError('Invalid Squid queue trial ID')
    return FOLDER/(trial_id+'.json')

def review(service,cfg,direction,trial_id):
    output=output_path(trial_id)
    if output.exists():raise TransferError('Squid queue trial already attempted; keep original evidence')
    state=preflight(service);plan,path,speeds=route(direction)
    near(state['pose_mm'],path[0],.05)
    start={k:state['pose_mm'][k] for k in KEYS}
    path[1]={**start,'Z':path[1]['Z']}
    points=[quantize(p) for p in path[1:]]
    check_route(start,points,state['joints'],cfg,service.envelope)
    e1=state.get('external_axes',{}).get('E1')
    if type(e1) not in (int,float) or not math.isfinite(e1):raise TransferError('Missing grip feedback')
    cap=LuaTrajectory(service).capability()
    if not cap.get('available') or cap.get('version')!=SEGMENT_SPEED_VERSION:
        raise TransferError('Publish Lua queue 220109 before one-queue Squid travel; no motion sent')
    return dict(direction=direction,trial_id=trial_id,source_sha256=CURRENT_SHA,start=start,
        points=points,joints=state['joints'],e1=e1,cfg=cfg,envelope=plan['envelope'],speeds=speeds,
        protocol=SEGMENT_SPEED_VERSION,zone=-1)

def execute(run,service,cfg,approved):
    fresh=review(service,cfg,approved['direction'],approved['trial_id'])
    for key in ('source_sha256','points','cfg','envelope','speeds','protocol','zone'):
        if fresh[key]!=approved[key]:raise TransferError('Squid queue plan changed')
    near(fresh['start'],approved['start'],.05)
    if abs(fresh['e1']-approved['e1'])>.05 or any(abs(fresh['joints'][k]-approved['joints'][k])>.5 for k in ('J1','J2','J3','J4')):
        raise TransferError('Squid queue start/grip changed')
    output=output_path(fresh['trial_id']);output.parent.mkdir(exist_ok=True)
    record=dict(status='started',at=time.time(),plan=fresh,samples=[],source_state=service.status(),
        release_executed=False,gripper_commands=[],startup_commands=[],hardware_acceptance=None)
    with output.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    def save():output.write_text(json.dumps(record,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    holding=HoldingService(service,fresh['e1'],fresh['envelope'])
    def progress(stage,done,total):
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=service.status()))
        run.say(f'Squid single queue: {stage} {done:.1f}/{total}')
    try:
        result=LuaTrajectory(holding).execute(run,fresh['start'],fresh['joints'],fresh['points'],cfg,137,progress,
            reviewed=True,squid_queue=True,segment_speeds=fresh['speeds'])
        record.update(status='completed_pending_operator_assessment',result=result)
        return dict(result,record=str(output),direction=fresh['direction'])
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error));raise
    finally:
        record.update(finished_at=time.time(),final_robot=service.status());save()
