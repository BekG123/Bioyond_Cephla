"""Supervised 48-well long-side slot2 pickup; proof lift then accepted return."""
import hashlib
import json
import math
import time
from pathlib import Path
from uuid import uuid4
from autonomy import TransferError
from scope_step_trial import preflight,near
from home_hamilton_exchange import native
from plan_hotel_slot1 import SESSION,KEYS
from plan_hotel_slot2 import build_revised_slot2
from plan_short_side_hamilton import validate
from gripper_closure import closure_commands,grip_feedback_matches,POLICY
from run_record_io import write_run_record

PLAN=SESSION/'slot_2_candidate_v2.json'
OUTPUT=SESSION/'slot2_trials'


def geometry():
    raw=PLAN.read_bytes();d=json.loads(raw);fresh=build_revised_slot2()
    fresh['at']=d['at']
    if json.loads(json.dumps(fresh))!=d:raise TransferError('Slot2 reference changed.')
    seat=d['points'][-1];proof=dict(seat,Z=seat['Z']+5)
    q=d['forward_validation']['endpoint_joints'];lift_q=dict(q,J1=q['J1']+5)
    reverse=[dict(d['points'][2],Z=proof['Z']),d['points'][1],d['points'][0],d['start']]
    routes={
        'slot2_approach':dict(start=d['start'],points=d['points'],speeds=[137,137,5,5],expected=q,e1=28),
        'slot2_lift':dict(start=seat,points=[proof],speeds=[5],expected=lift_q,e1=3.9),
        'slot2_return':dict(start=proof,points=reverse,speeds=[5,5,137,137],expected=d['start_joints'],e1=3.9)}
    for name,r in routes.items():
        start_q=d['start_joints'] if name=='slot2_approach' else q if name=='slot2_lift' else lift_q
        v=validate(r['start'],r['points'],start_q,d['config'],d['envelope'],r['expected'])
        if not v['workspace_valid']:raise TransferError('Slot2 route exceeds workspace.')
    return dict(candidate_sha256=hashlib.sha256(raw).hexdigest(),cfg=d['config'],envelope=d['envelope'],
        routes=routes,plate='48-well',grip_sides='long',grip_target=3.9,closure_policy=POLICY,proof_lift_mm=5)


def state(service,expected_e1=None,stationary=True):
    s=preflight(service);n=native(service)
    if not s.get('enabled') or s.get('program_state',{}).get('state')!='running':
        raise TransferError('Healthy running Auto required; no restart or reset.')
    if stationary and n['moving']:raise TransferError('Arm not stationary.')
    axes=n['external_axes']
    if any(not math.isfinite(axes[k]) for k in ('E1','E2')):raise TransferError('Invalid external-axis feedback.')
    if expected_e1 is not None:
        match=grip_feedback_matches(axes['E1'],3.9) if expected_e1==3.9 else abs(axes['E1']-expected_e1)<=.15
        if not match:
            raise TransferError(f"Jaw feedback differs from required payload state: actual E1={axes['E1']:.6f} mm, expected {expected_e1:.6f} mm.")
    return s,n


def preview(service,cfg,phase='pickup',source=None):
    if phase not in ('pickup','return'):raise TransferError('Unknown slot2 phase.')
    g=geometry();s,n=state(service,0 if phase=='pickup' else 3.9)
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
        raise TransferError('Slot2 geometry/workspace changed.')
    route=g['routes']['slot2_approach' if phase=='pickup' else 'slot2_return']
    near(s['pose_mm'],route['start'],.05)
    binding={}
    if phase=='return':
        source=Path(source).resolve()
        if source.parent!=OUTPUT.resolve():raise TransferError('Unexpected pickup receipt.')
        raw=source.read_bytes();r=json.loads(raw)
        if r.get('status')!='proof_lift_completed_retention_pending' or r['plan']['geometry']!=g or not 0<=time.time()-r['finished_at']<=1800:
            raise TransferError('Fresh completed unchanged proof lift required.')
        near(s['pose_mm'],r['final']['pose_mm'],.05)
        if abs(n['external_axes']['E2']-r['final_native']['external_axes']['E2'])>.1:raise TransferError('Holder changed since pickup.')
        for existing in OUTPUT.glob('*.json'):
            previous=json.loads(existing.read_bytes())
            if previous.get('plan',{}).get('source')==str(source):raise TransferError('Return already attempted; no retry.')
        binding=dict(source=str(source),source_sha256=hashlib.sha256(raw).hexdigest())
    elif source is not None:raise TransferError('Pickup must not have a source receipt.')
    q=s['joints'];pos=s['pose_mm']
    phases=['slot2_approach','slot2_lift'] if phase=='pickup' else ['slot2_return']
    for name in phases:
        route=g['routes'][name]
        v=validate(pos,route['points'],q,cfg,service.envelope,route['expected'])
        if not v['workspace_valid']:raise TransferError('Live slot2 IK failed.')
        q=v['endpoint_joints'];pos=route['points'][-1]
    return dict(id=uuid4().hex,at=time.time(),phase=phase,geometry=g,start=s['pose_mm'],joints=s['joints'],
        axes=n['external_axes'],**binding)


class Slot2Service:
    def __init__(self,owner,plan):self.owner=owner;self.plan=plan;self.expected_e1=28
    def __getattr__(self,name):return getattr(self.owner,name)
    def _preflight(self):
        refusal=self.owner._preflight()
        if refusal:return refusal
        try:
            _,n=state(self.owner,self.expected_e1,False)
            if abs(n['external_axes']['E2']-self.plan['axes']['E2'])>.1:return 'Holder changed during slot2 trial.'
        except Exception as e:return str(e)
        return None


def prepare_for_service(service,phase,start,joints,points,cfg,envelope,speeds):
    if not isinstance(service,Slot2Service):raise TransferError('Bound slot2 service required.')
    g=geometry()
    if service.plan['geometry']!=g or cfg!=g['cfg'] or {k:list(v) for k,v in envelope.items()}!=g['envelope']:
        raise TransferError('Slot2 reference changed.')
    allowed=('slot2_approach','slot2_lift') if service.plan['phase']=='pickup' else ('slot2_return',)
    if phase not in allowed:raise TransferError('Wrong slot2 phase.')
    r=g['routes'][phase];near(start,r['start'],.05)
    if points!=r['points'] or list(speeds)!=r['speeds'] or service.expected_e1!=r['e1']:
        raise TransferError('Slot2 route/speed/payload differs from reviewed phase.')
    out=[{k:math.floor(p[k]*100+.5)/100 for k in KEYS} for p in points]
    v=validate(start,out,joints,cfg,envelope,r['expected'])
    if not v['workspace_valid']:raise TransferError('Slot2 workspace exceeded.')
    return out,v['endpoint_joints']


def execute(run,service,cfg,approved):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Slot2 preview expired.')
    fresh=preview(service,cfg,approved['phase'],approved.get('source'))
    for k in ('phase','geometry','source','source_sha256'):
        if fresh.get(k)!=approved.get(k):raise TransferError('Slot2 plan changed.')
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in fresh['joints']) or any(abs(fresh['axes'][k]-approved['axes'][k])>.1 for k in ('E1','E2')):
        raise TransferError('Slot2 starting feedback changed.')
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/(fresh['id']+'.json')
    record=dict(status='starting',at=time.time(),plan=fresh,steps=[],samples=[],motion_sent=False,
        plate_and_clearance_confirmed=True,retention_confirmed=fresh['phase']=='return',automatic_retries=False)
    owner=Slot2Service(service,fresh);expected=0 if fresh['phase']=='pickup' else 3.9
    def save():write_run_record(path,record)
    def check(stationary=False,check_jaw=True):
        if run.stopped():raise TransferError('Slot2 trial stopped.')
        s,n=state(service,expected if check_jaw else None,stationary)
        if abs(n['external_axes']['E2']-fresh['axes']['E2'])>.1:raise TransferError('Holder changed during slot2 trial.')
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
        return s,n
    def require(result):
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):raise TransferError('Slot2 command failed/uncertain; no retry: '+str(result))
        return result
    def jaws(target,speed):
        nonlocal expected
        before,_=check(True);item=dict(kind='gripper',target=target,speed=speed,status='dispatching')
        record['steps'].append(item);record['motion_sent']=True;save()
        result=require(service.move_gripper(target,speed));item['result']=result;save()
        expected=target
        for _ in range(3):
            after,n=check(True);near(after['pose_mm'],before['pose_mm'],.05);time.sleep(.1)
        item.update(status='completed',actual=n['external_axes']['E1']);save()
    def queued(phase):
        from trajectory_queue import LuaTrajectory
        s,_=check(True);route=fresh['geometry']['routes'][phase];owner.expected_e1=expected
        prepare_for_service(owner,phase,s['pose_mm'],s['joints'],route['points'],cfg,service.envelope,route['speeds'])
        run.say(phase);record['motion_sent']=True;save()
        item=dict(kind=phase,status='dispatching');record['steps'].append(item);save()
        result=require(LuaTrajectory(owner).execute(run,s['pose_mm'],s['joints'],route['points'],cfg,137,
            lambda *args:check(),reviewed=True,segment_speeds=route['speeds'],hotel_route=phase))
        after,_=check(True);near(after['pose_mm'],route['points'][-1],.05)
        item.update(status='completed',result=result);save()
    save()
    try:
        check(True)
        if fresh['phase']=='pickup':
            run.say('Open empty jaws to28 before slot2 approach.');jaws(28,5)
            queued('slot2_approach')
            run.say('48-well long-side grip: approach10, final1mm at5 to3.9.')
            for c in closure_commands(28,3.9):jaws(c['target_e1_mm'],c['speed'])
            queued('slot2_lift');status='proof_lift_completed_retention_pending'
        else:
            queued('slot2_return');status='returned_HOME_held_pending_assessment'
        s,n=check(True);record.update(status=status,final=s,final_native=n)
        return dict(ok=True,status=status,record=str(path),pose_mm=s['pose_mm'],payload='held_pending_inspection')
    except BaseException as e:
        record.update(status='stopped_or_uncertain',error=str(e))
        if record['motion_sent']:
            try:record['stop']=service.program('stop')
            except Exception as stop:record['stop_error']=str(stop)
        raise
    finally:record['finished_at']=time.time();save()
