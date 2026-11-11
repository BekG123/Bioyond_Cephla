"""Reviewed, bounded departure from the stopped November 8 Hamilton column."""
from copy import deepcopy
import json
import math
import time
from pathlib import Path
from autonomy import check_path,TransferError,wrap
from scope_step_trial import near,preflight
import hamilton_reteach_trial as taught

ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT/'reports/integrated_dry_mock_site6_20261110/recovery_home_retry01.json'

def plan(state,cfg,envelope):
    source=taught.reference();start={k:state['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    seat,hover,boundary,home=source['routes']['reverse']
    if (math.hypot(start['X']-seat['X'],start['Y']-seat['Y'])>2.5 or
        abs(wrap(start['Rz']-seat['Rz']))>2 or not seat['Z']<=start['Z']<=hover['Z']):
        raise TransferError('Stopped pose outside the reviewed Hamilton departure column')
    if any(value!=source['cfg'].get(key) for key,value in cfg.items()) or {k:list(v) for k,v in envelope.items()}!=source['parent']['envelope']:
        raise TransferError('Recovery settings changed')
    high={**start,'Z':hover['Z']}
    vertices=[start,high,hover,boundary,home]
    speeds=[5,5,40,40]
    q=deepcopy(state['joints']);offset=q['J1']-start['Z'];count=0;groups=[]
    for i,(a,b) in enumerate(zip(vertices,vertices[1:])):
        # Only these explicitly reviewed column/hover/exit segments have a local
        # station exception. The workspace itself remains enabled and unchanged.
        env=envelope if i==3 else None
        n=max(1,math.ceil(math.dist([a[k] for k in ('X','Y','Z')],[b[k] for k in ('X','Y','Z')])),math.ceil(abs(wrap(b['Rz']-a['Rz']))/.5))
        previous=a
        for j in range(1,n+1):
            p={k:a[k]+(b[k]-a[k])*j/n for k in ('X','Y','Z','Rz')}
            q=check_path(previous,p,q,cfg,env);q['J1']=p['Z']+offset
            if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Recovery exceeds joint travel')
            previous=p;count+=1
        segments=max(1,math.ceil(math.dist([a[k] for k in ('X','Y','Z')],[b[k] for k in ('X','Y','Z')])/40))
        points=[{k:round(a[k]+(b[k]-a[k])*j/segments,2) for k in ('X','Y','Z','Rz')} for j in range(1,segments+1)]
        groups.append(dict(points=points,speed=speeds[i]))
    e1=state['external_axes']['E1']
    if not isinstance(e1,(int,float)) or not math.isfinite(e1):raise TransferError('Claw feedback missing')
    return dict(start=start,joints=state['joints'],e1=e1,groups=groups,vertices=vertices,
        cfg=cfg,envelope=envelope,dense_samples=count,candidate_sha256=taught.SHA)

def review(service,cfg):
    if OUTPUT.exists():raise TransferError('Recovery already attempted; preserve evidence')
    s=preflight(service)
    if not service.envelope_enabled:raise TransferError('Workspace must remain enabled')
    if not (s['enabled'] and s['control_mode']['mode']=='auto' and s['program_state']['state']=='running'):
        raise TransferError('Recovery requires running Auto; no startup')
    return plan(s,cfg,service.envelope)

def execute(run,service,cfg,approved):
    from trajectory_queue import LuaTrajectory
    fresh=review(service,cfg)
    near(fresh['start'],approved['start'],.02)
    if abs(fresh['e1']-approved['e1'])>.05:raise TransferError('Jaw changed since recovery review')
    record=dict(status='running',plan=fresh,at=time.time(),samples=[],gripper_commands=[],
        authorization='Operator confirmed collision corrected, plate securely held, clear straight-up retreat and Home route; requested Home first. Preserve current jaw opening.')
    OUTPUT.parent.mkdir(exist_ok=True,parents=True)
    with OUTPUT.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    def save():OUTPUT.write_text(json.dumps(record,indent=2),encoding='utf-8')
    def monitor(stage,done,total):
        s=preflight(service)
        if run.stopped() or abs(s['external_axes']['E1']-fresh['e1'])>.1:raise TransferError('Recovery stopped or jaw position changed')
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=s));save()
    try:
        for group in fresh['groups']:
            monitor('before_leg',0,1);s=preflight(service)
            LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],group['points'],cfg,group['speed'],monitor,reviewed=True)
            near(service.pose_mm(),group['points'][-1],.1)
        final=preflight(service);near(final['pose_mm'],fresh['vertices'][-1],.1)
        record.update(status='completed',final_robot=final)
        return dict(ok=True,home=True,preserved_e1=fresh['e1'],report=str(OUTPUT))
    except Exception as e:
        record.update(status='failed_or_uncertain',error=str(e));raise
    finally:
        record['finished_at']=time.time();save()
