"""One supervised trial per direction of the immutable 26 October proposal."""
from copy import deepcopy
import hashlib
import json
import math
import time
from autonomy import check_path, TransferError
from hamilton_true_home import ROOT, configured, segment_envelope
from scope_step_trial import near, preflight

PLAN=ROOT/'reports/trajectory_smoothing/hamilton_reteach_20261026/candidate.json'
SHA='4883914f3c350a34eb4f899d8bff20bf9606bd4905c553d7403e22a14f9393bf'
OUTPUT=PLAN.with_name('forward_speed137_trial.json')


def output_path(reverse=False):
    return OUTPUT.with_name('reverse_speed137_trial.json') if reverse else OUTPUT


def reference():
    raw=PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise TransferError('Hamilton trial proposal changed.')
    plan=json.loads(raw)
    current=configured()
    promoted=current.get('accepted_candidate_sha256')==SHA
    for name,digest in plan['source_hashes'].items():
        if promoted and name=='hamilton_endpoint.json':continue
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise TransferError('Hamilton trial source changed: '+name)
    if (not promoted and current!=plan['parent']) or (promoted and current['forward']!=plan['routes']['forward']):
        raise TransferError('Hamilton parent route changed.')
    return plan


def validate_route(start,points):
    plan=reference()
    for path in plan['routes'].values():
        if points==path[1:]:
            near(start,path[0],.05)
            return plan
    raise TransferError('Only the exact approved Hamilton trial points are allowed.')


def check_route(start,points,joints,cfg,envelope):
    plan=validate_route(start,points)
    if any(cfg[k]!=plan['cfg'].get(k) for k in cfg):raise TransferError('Hamilton trial joint settings changed.')
    if {k:list(v) for k,v in envelope.items()}!=plan['parent']['envelope']:
        raise TransferError('Hamilton trial workspace changed.')
    q=deepcopy(joints);offset=q['J1']-start['Z'];previous=start
    reverse=points==plan['routes']['reverse'][1:]
    if not 0<=q['J1']<=400:raise TransferError('Hamilton trial J1 limit.')
    for index,point in enumerate(points):
        # Operator approved this exact replacement segment after reviewing the
        # diagonal descent. This is not a general workspace expansion.
        env=None if index==(0 if reverse else 2) else segment_envelope(previous,point,envelope,plan['parent'])
        q=check_path(previous,point,q,cfg,env);q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Hamilton trial J1/J3 limit.')
        previous=point
    measured=plan['validation']['reverse']['checked'][-1]['joints'] if reverse else plan['measured_joints']
    if any(abs(q[k]-measured[k])>.5 for k in ('J1','J2','J3','J4')):
        raise TransferError('Hamilton trial arrival joint configuration differs from teaching.')
    return q


def review(service,cfg,reverse=False):
    if output_path(reverse).exists():raise TransferError('Hamilton trial already attempted; review before any retry.')
    forward_hash=None
    if reverse:
        raw=OUTPUT.read_bytes();forward=json.loads(raw)
        if forward['status']!='completed' or forward['plan']['candidate_sha256']!=SHA or forward['result'].get('ok') is not True:
            raise TransferError('Successful matching forward trial required before returning.')
        forward_hash=hashlib.sha256(raw).hexdigest()
    state=preflight(service);plan=reference();path=plan['routes']['reverse' if reverse else 'forward']
    near(state['pose_mm'],path[0],.05)
    check_route(path[0],path[1:],state['joints'],cfg,service.envelope)
    e1=state.get('external_axes',{}).get('E1')
    if type(e1) not in (int,float) or not math.isfinite(e1):raise TransferError('Claw feedback unavailable.')
    return dict(candidate_sha256=SHA,start=path[0],points=path[1:],
                joints=state['joints'],e1=e1,speed=137,reverse=reverse,forward_trial_sha256=forward_hash)


def execute(run,service,cfg,approved):
    fresh=review(service,cfg,approved.get('reverse',False));output=output_path(fresh['reverse'])
    if any(fresh[k]!=approved[k] for k in ('candidate_sha256','start','points','speed','reverse','forward_trial_sha256')):
        raise TransferError('Hamilton trial changed before dispatch.')
    if abs(fresh['e1']-approved['e1'])>.05:raise TransferError('Claw changed before dispatch.')
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.5 for k in ('J1','J2','J3','J4')):
        raise TransferError('Home joint configuration changed before dispatch.')
    record=dict(status='started',started_at=time.time(),plan=fresh,before=service.status(),samples=[],
        authorization=('Operator accepted the forward trial and requested the same path back to Home; supervised session continues.' if fresh['reverse'] else
                       'Operator requested this saved proposal now from Home, E-stop supervised and hands clear, after disclosure of the diagonal final approach.'),
        gripper_commands=False,program_restart=False,operator_acceptance=None)
    with output.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def progress(stage,done,total):
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=service.status()))
        run.say(f'Hamilton revised endpoint: {stage} {done:.1f}/{total}')
        e1=service.external_axes().get('E1')
        if type(e1) not in (int,float) or not math.isfinite(e1) or abs(e1-fresh['e1'])>.1:
            raise TransferError('Claw feedback changed during Hamilton trial.')
    try:
        from trajectory_queue import LuaTrajectory
        result=LuaTrajectory(service).execute(run,fresh['start'],fresh['joints'],fresh['points'],cfg,137,
            progress,reviewed=True,home_speed137=True,hamilton_trial=True)
        record.update(status='completed',result=result)
        return result
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error))
        raise
    finally:
        record.update(finished_at=time.time(),final_robot=service.status())
        output.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
