"""Pinned empty-arm HOME connector and slot1 Path A trial; no plate handling."""
import hashlib
import json
import math
import time
from pathlib import Path
from uuid import uuid4
from autonomy import TransferError
from home_hamilton_exchange import native
from plan_hotel_slot1 import SESSION,build,KEYS
from plan_short_side_hamilton import validate
from scope_step_trial import near
from run_record_io import write_run_record

PLAN=SESSION/'slot_1_route_candidates_v1.json'
ANCHOR=dict(X=341.013,Y=-5.404,Z=238.159,Rz=50.525)
OUTPUT=SESSION/'trials'
FORWARD_RECEIPT=OUTPUT/'fa026660e6e3499aa0d58335195321a8.json'


def reference():
    d=json.loads(PLAN.read_bytes());fresh=json.loads(json.dumps(build()))
    if d!=fresh:raise TransferError('Hotel candidate/reference changed; review again.')
    return d,hashlib.sha256(PLAN.read_bytes()).hexdigest()


def snapshot(service):
    s=service.status();n=native(service)
    if not s.get('connected') or not s.get('ok') or s.get('errors') or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
        raise TransferError('Stationary fault-free Auto required.')
    if not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1'])>.15:
        raise TransferError('Expected operator-confirmed empty, closed jaws; no automatic opening.')
    if not service.envelope_enabled:raise TransferError('Workspace checks must remain enabled.')
    return s,n


def reverse_reference():
    d,digest=reference()
    raw=FORWARD_RECEIPT.read_bytes();r=json.loads(raw)
    if r['status']!='completed_empty_slot1_trial' or r['plan']['candidate_sha256']!=digest:
        raise TransferError('Completed forward Path A evidence required.')
    points=d['candidates']['compact_three']['points']
    near(r['final']['pose_mm'],points[-1],.05)
    return d,digest,hashlib.sha256(raw).hexdigest()


def preview(service,cfg,direction='forward'):
    if direction=='cycle':
        d,digest,source_hash=reverse_reference();s,n=snapshot(service)
        near(s['pose_mm'],d['start'],.05)
        if cfg!=d['config'] or {k:list(v) for k,v in service.envelope.items()}!=d['envelope']:
            raise TransferError('Hotel cycle geometry/workspace changed.')
        if not s['enabled'] or s['program_state']['state']!='running':
            raise TransferError('Cycle requires healthy running controller; no automatic startup.')
        f=d['candidates']['compact_three'];reverse=[f['points'][1],f['points'][0],d['start']]
        forward_check=validate(s['pose_mm'],f['points'],s['joints'],cfg,service.envelope,f['validation']['endpoint_joints'])
        backward_check=validate(f['points'][-1],reverse,forward_check['endpoint_joints'],cfg,service.envelope,d['start_joints'])
        if not forward_check['workspace_valid'] or not backward_check['workspace_valid']:
            raise TransferError('Hotel cycle exceeds workspace.')
        return dict(id=uuid4().hex,at=time.time(),direction='cycle',candidate_sha256=digest,
            forward_receipt_sha256=source_hash,start=s['pose_mm'],joints=s['joints'],axes=n['external_axes'],
            cfg=cfg,envelope=d['envelope'],routes={
                'path_a':dict(start=d['start'],points=f['points'],speeds=[137,137,5],expected=f['validation']['endpoint_joints']),
                'reverse':dict(start=f['points'][-1],points=reverse,speeds=[5,137,137],expected=d['start_joints'])},
            payload='empty',finish='One slot1 round trip; end HOME clearance with jaws unchanged.')
    if direction=='reverse':
        d,digest,source_hash=reverse_reference();s,n=snapshot(service)
        points=d['candidates']['compact_three']['points']
        near(s['pose_mm'],points[-1],.05)
        if cfg!=d['config'] or {k:list(v) for k,v in service.envelope.items()}!=d['envelope']:
            raise TransferError('Hotel reverse geometry/workspace changed.')
        if not s['enabled'] or s['program_state']['state']!='running':
            raise TransferError('Reverse requires healthy running controller; no automatic startup.')
        reverse=[points[1],points[0],d['start']]
        v=validate(s['pose_mm'],reverse,s['joints'],cfg,service.envelope,d['start_joints'])
        if not v['workspace_valid']:raise TransferError('Reverse violates workspace.')
        return dict(id=uuid4().hex,at=time.time(),direction='reverse',candidate_sha256=digest,
            forward_receipt_sha256=source_hash,start=s['pose_mm'],joints=s['joints'],axes=n['external_axes'],
            cfg=cfg,envelope=d['envelope'],routes={'reverse':dict(start=points[-1],points=reverse,
                speeds=[5,137,137],expected=d['start_joints'])},payload='empty',finish='HOME clearance; jaws unchanged.')
    if direction!='forward':raise TransferError('Unknown hotel direction.')
    d,digest=reference();s,n=snapshot(service)
    near(s['pose_mm'],ANCHOR,.1)
    if cfg!=d['config'] or {k:list(v) for k,v in service.envelope.items()}!=d['envelope']:
        raise TransferError('Hotel trial geometry/workspace changed.')
    home=d['start'];connector=[dict(home,Z=s['pose_mm']['Z']),home]
    check=validate(s['pose_mm'],connector,s['joints'],cfg,service.envelope,d['start_joints'])
    if not check['workspace_valid']:raise TransferError('HOME connector violates workspace.')
    return dict(id=uuid4().hex,at=time.time(),candidate_sha256=digest,start=s['pose_mm'],
        joints=s['joints'],axes=n['external_axes'],cfg=cfg,envelope=d['envelope'],
        routes={'home':dict(start=s['pose_mm'],points=connector,speeds=[40,5],expected=d['start_joints']),
                'path_a':dict(start=home,points=d['candidates']['compact_three']['points'],speeds=[137,137,5],
                    expected=d['candidates']['compact_three']['validation']['endpoint_joints'])},
        payload='empty',finish='Stop at slot1 with jaws unchanged; no release or grip.')


class HotelService:
    def __init__(self,service,plan):self.owner=service;self.plan=plan
    def __getattr__(self,name):return getattr(self.owner,name)
    def _preflight(self):
        refusal=self.owner._preflight()
        if refusal:return refusal
        n=native(self.owner)
        if abs(n['external_axes']['E1'])>.15:return 'Hotel trial jaw position changed.'
        if abs(n['external_axes']['E2']-self.plan['axes']['E2'])>.1:return 'Holder moved during hotel trial.'
        return None


def prepare_for_service(service,phase,start,joints,points,cfg,envelope,speeds):
    if phase.startswith('slot3_handling_'):
        from hotel_slot3_handling import prepare_for_service as prepare_handling3
        return prepare_handling3(service,phase,start,joints,points,cfg,envelope,speeds)
    if phase.startswith('slot2_handling_'):
        from hotel_slot2_handling import prepare_for_service as prepare_handling
        return prepare_handling(service,phase,start,joints,points,cfg,envelope,speeds)
    if phase in ('slot2_taught_approach','slot3_taught_approach'):
        from hotel_slot2_trial import prepare_for_service as prepare_slot2
        return prepare_slot2(service,phase,start,joints,points,cfg,envelope,speeds)
    if phase.startswith('slot1_retrieval_'):
        from hotel_slot1_retrieval import prepare_for_service as prepare_retrieval
        return prepare_retrieval(service,phase,start,joints,points,cfg,envelope,speeds)
    if phase.startswith('slot1_delivery_'):
        from hotel_slot1_delivery import prepare_for_service as prepare_delivery
        return prepare_delivery(service,phase,start,joints,points,cfg,envelope,speeds)
    if phase=='slot1_lower_recovery':
        from hotel_slot1_lower_recovery import prepare_for_service as prepare_lower
        return prepare_lower(service,phase,start,joints,points,cfg,envelope,speeds)
    if phase=='slot1_empty_recovery':
        from hotel_slot1_empty_recovery import prepare_for_service as prepare_empty
        return prepare_empty(service,phase,start,joints,points,cfg,envelope,speeds)
    if phase in ('home48_connect','home48_descend','home48_lift'):
        from hotel_home_pickup import prepare_for_service as prepare_home
        return prepare_home(service,phase,start,joints,points,cfg,envelope,speeds)
    if phase=='slot2_recovery':
        from hotel_slot2_recovery import prepare_for_service as prepare_recovery
        return prepare_recovery(service,phase,start,joints,points,cfg,envelope,speeds)
    if phase in ('slot2_approach','slot2_lift','slot2_return'):
        from hotel_slot2_pickup import prepare_for_service as prepare_slot2
        return prepare_slot2(service,phase,start,joints,points,cfg,envelope,speeds)
    if not isinstance(service,HotelService) or phase not in ('home','path_a','reverse'):
        raise TransferError('Hotel trial requires its bound empty-arm service.')
    d,digest=reference();p=service.plan
    if digest!=p['candidate_sha256'] or cfg!=d['config'] or {k:list(v) for k,v in envelope.items()}!=d['envelope']:
        raise TransferError('Hotel geometry changed.')
    if phase=='reverse':
        _,_,source_hash=reverse_reference()
        if p.get('direction') not in ('reverse','cycle') or p.get('forward_receipt_sha256')!=source_hash:
            raise TransferError('Reverse must bind completed forward evidence.')
        forward=d['candidates']['compact_three']['points']
        expected_points=[forward[1],forward[0],d['start']]
        near(p['start'],d['start'] if p.get('direction')=='cycle' else forward[-1],.05);near(start,forward[-1],.05)
        expected_speeds=[5,137,137]
    else:
        if p.get('direction')=='reverse':raise TransferError('Wrong direction.')
        expected_home=[dict(d['start'],Z=p['start']['Z']),d['start']]
        expected_points=expected_home if phase=='home' else d['candidates']['compact_three']['points']
        expected_start=p['start'] if phase=='home' else d['start']
        if p.get('direction')=='cycle':
            _,_,source_hash=reverse_reference()
            if phase!='path_a' or p.get('forward_receipt_sha256')!=source_hash:raise TransferError('Invalid cycle phase/evidence.')
            near(p['start'],d['start'],.05)
        else:near(p['start'],ANCHOR,.1)
        near(start,expected_start,.05)
        expected_speeds=[40,5] if phase=='home' else [137,137,5]
    if points!=expected_points or list(speeds)!=expected_speeds:
        raise TransferError('Hotel points/speeds differ from reviewed candidate.')
    out=[{k:math.floor(v[k]*100+.5)/100 for k in KEYS} for v in points]
    expected=d['start_joints'] if phase in ('home','reverse') else d['candidates']['compact_three']['validation']['endpoint_joints']
    v=validate(start,out,joints,cfg,envelope,expected)
    if not v['workspace_valid']:raise TransferError('Hotel path exceeds workspace.')
    return out,v['endpoint_joints']


def execute(run,service,cfg,approved):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Hotel preview expired.')
    fresh=preview(service,cfg,approved.get('direction','forward'))
    near(fresh['start'],approved['start'],.05)
    for k in ('candidate_sha256','cfg','envelope'):
        if fresh[k]!=approved[k]:raise TransferError('Hotel plan changed.')
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in fresh['joints']):raise TransferError('Joint start changed.')
    if any(abs(fresh['axes'][k]-approved['axes'][k])>.1 for k in ('E1','E2')):raise TransferError('External axes changed.')
    if approved['routes']!=fresh['routes']:raise TransferError('Path A changed.')
    if fresh.get('forward_receipt_sha256')!=approved.get('forward_receipt_sha256'):raise TransferError('Forward evidence changed.')
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/(fresh['id']+'.json')
    r=dict(status='starting',at=time.time(),plan=fresh,empty_jaws_confirmed=True,route_clear_confirmed=True,
        steps=[],samples=[],motion_sent=False,startup_sent=False,automatic_retries=False)
    def save():write_run_record(path,r)
    def require(v):
        if not v.get('ok') or v.get('recovered'):raise TransferError('Command failed or uncertain; no retry: '+str(v))
        return v
    def monitor(*args):
        if run.stopped():raise TransferError('Hotel trial stopped.')
        s=service.status();n=native(service)
        if s.get('errors') or not s.get('enabled') or s['program_state']['state']!='running' or any(n.get(k,True) for k in ('error','emergency','drag','manual')):
            raise TransferError('Controller unhealthy during hotel trial.')
        if abs(n['external_axes']['E1'])>.15 or abs(n['external_axes']['E2']-fresh['axes']['E2'])>.1:
            raise TransferError('Jaw/holder changed; stop empty trial.')
        r['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
    save()
    try:
        if run.stopped():raise TransferError('Stopped before startup.')
        s,_=snapshot(service)
        if s['program_state']['state']!='running':
            r['startup_sent']=True;save()
            if s['program_state']['state']!='stopped':require(service.program('stop'))
            near(service.status()['pose_mm'],fresh['start'],.05)
            if not service.status()['enabled']:require(service.set_enable(True,True))
            require(service.program('start',force=True))
        monitor();near(service.status()['pose_mm'],fresh['start'],.05)
        from trajectory_queue import LuaTrajectory
        owner=HotelService(service,fresh);queue=LuaTrajectory(owner)
        for phase in (('path_a','reverse') if fresh.get('direction')=='cycle' else fresh['routes']):
            monitor();s=service.status();route=fresh['routes'][phase]
            prepare_for_service(owner,phase,s['pose_mm'],s['joints'],route['points'],cfg,service.envelope,route['speeds'])
            run.say('Reverse Path A to HOME; slot exit at5, remaining travel137.' if phase=='reverse' else ('Return empty arm to HOME.' if phase=='home' else 'Path A: three targets, final insertion at5; stop at slot1.'))
            r['motion_sent']=True;save()
            result=require(queue.execute(run,s['pose_mm'],s['joints'],route['points'],cfg,137,monitor,
                reviewed=True,segment_speeds=route['speeds'],hotel_route=phase))
            r['steps'].append(dict(phase=phase,result=result));save();monitor()
        r.update(status=('completed_empty_slot1_cycle' if fresh.get('direction')=='cycle' else 'completed_empty_home_return' if fresh.get('direction')=='reverse' else 'completed_empty_slot1_trial'),final=service.status(),final_native=native(service))
        return dict(ok=True,record=str(path),pose_mm=r['final']['pose_mm'],payload='empty')
    except BaseException as e:
        r.update(status='stopped_or_uncertain',error=str(e))
        if r['motion_sent'] or r['startup_sent']:
            try:r['stop']=service.program('stop')
            except Exception as stop:r['stop_error']=str(stop)
        raise
    finally:r['finished_at']=time.time();save()
