"""Pinned empty-arm return after the operator manually withdrew from slot 1."""
import json
import math
import time
from uuid import uuid4
from autonomy import TransferError
from hotel_slot_trial import reference,HotelService
from home_hamilton_exchange import native
from plan_hotel_slot1 import SESSION,KEYS
from plan_short_side_hamilton import validate
from scope_step_trial import near
from run_record_io import write_run_record

ANCHOR=dict(X=113.826,Y=-139.407,Z=240.596,Rz=.53)
OUTPUT=SESSION.parent/'hotel_slot1_loaded_teaching_20261111_222406'/'empty_recovery'


def points_for(start,home):
    return [dict(start,X=205),dict(X=240.,Y=25.,Z=250.44,Rz=.752),home]


def checked(start,points,joints,cfg,envelope,expected):
    near(start,ANCHOR,.05)
    v=validate(start,points,joints,cfg,envelope,expected)
    for item in v['workspace_violations']:
        p=item['pose']
        if item['segment']!=0 or set(item['outside'])!={'X'} or not start['X']-.001<=p['X']<200:
            raise TransferError('Recovery exception is only the monotonic X entry from this confirmed start.')
        near(dict(p,X=start['X']),start,.006)
    return v


def snapshot(service):
    s=service.status();n=native(service)
    if not s.get('connected') or not s.get('ok') or s.get('errors') or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
        raise TransferError('Stationary fault-free Auto required.')
    if not math.isfinite(n['external_axes']['E1']) or min(abs(n['external_axes']['E1']-28),abs(n['external_axes']['E1']))>.15:
        raise TransferError('Operator-released empty jaws, fully open or closed, required before startup.')
    if not service.envelope_enabled:raise TransferError('Workspace checks must remain enabled.')
    return s,n


def preview(service,cfg):
    d,digest=reference();s,n=snapshot(service);near(s['pose_mm'],ANCHOR,.05)
    if s['program_state']['state']!='stopped':raise TransferError('Recovery requires the stopped empty-arm state.')
    if cfg!=d['config'] or {k:list(v) for k,v in service.envelope.items()}!=d['envelope']:
        raise TransferError('Recovery geometry/workspace changed.')
    start={k:s['pose_mm'][k] for k in KEYS};points=points_for(start,d['start'])
    checked(start,points,s['joints'],cfg,service.envelope,d['start_joints'])
    return dict(id=uuid4().hex,at=time.time(),start=start,joints=s['joints'],axes=n['external_axes'],
        candidate_sha256=digest,cfg=cfg,envelope=d['envelope'],points=points,speeds=[5]*3,
        workspace_exception='Only confirmed initial X113.826..200 ingress; global envelope unchanged.')


class RecoveryService(HotelService):pass


def prepare_for_service(service,phase,start,joints,points,cfg,envelope,speeds):
    if not isinstance(service,RecoveryService) or phase!='slot1_empty_recovery':raise TransferError('Bound recovery service required.')
    d,digest=reference();p=service.plan
    if cfg!=d['config'] or digest!=p['candidate_sha256'] or {k:list(v) for k,v in envelope.items()}!=d['envelope']:
        raise TransferError('Recovery geometry changed.')
    near(start,p['start'],.05)
    if points!=points_for(p['start'],d['start']) or list(speeds)!=[5]*3:raise TransferError('Exact recovery path/speed required.')
    out=[{k:math.floor(x[k]*100+.5)/100 for k in KEYS} for x in points]
    v=checked(start,out,joints,cfg,envelope,d['start_joints'])
    return out,v['endpoint_joints']


def execute(run,service,cfg,approved):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Recovery preview expired.')
    p=preview(service,cfg);near(p['start'],approved['start'],.05)
    for k in ('candidate_sha256','cfg','envelope','speeds'):
        if p[k]!=approved[k]:raise TransferError('Recovery plan changed.')
    for a,b in zip(p['points'],approved['points']):near(a,b,.05)
    if len(p['points'])!=len(approved['points']) or any(abs(p['joints'][k]-approved['joints'][k])>.1 for k in p['joints']) or any(abs(p['axes'][k]-approved['axes'][k])>.1 for k in ('E1','E2')):
        raise TransferError('Recovery starting state changed.')
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/(p['id']+'.json')
    r=dict(status='starting',plan=p,at=time.time(),empty_and_free_confirmed=True,route_clear_confirmed=True,
        events=[],samples=[],startup_sent=False,motion_sent=False,automatic_retries=False)
    def save():write_run_record(path,r)
    def require(v):
        if not v.get('ok') or v.get('recovered'):raise TransferError('Recovery failed or uncertain; no retry: '+str(v))
        return v
    def monitor(*args):
        if run.stopped():raise TransferError('Recovery stopped.')
        s=service.status();n=native(service)
        if not s.get('ok') or not s.get('enabled') or s.get('errors') or s['program_state']['state']!='running':raise TransferError('Recovery controller unhealthy.')
        if abs(n['external_axes']['E1'])>.15 or abs(n['external_axes']['E2']-p['axes']['E2'])>.1:raise TransferError('Recovery jaw/holder changed.')
        pose=s['pose_mm']
        if pose['X']<200:
            if pose['X']<p['start']['X']-.1:raise TransferError('Recovery moved farther outside workspace.')
            near(dict(pose,X=p['start']['X']),p['start'],.1)
        r['samples'].append(dict(at=time.time(),pose=pose,axes=n['external_axes']));save()
    save()
    try:
        if run.stopped():raise TransferError('Stopped before preparation.')
        if not service.status()['enabled']:
            r['startup_sent']=True;save();r['events'].append(require(service.set_enable(True,True)))
        near(service.status()['pose_mm'],p['start'],.05)
        if run.stopped():raise TransferError('Stopped before program start.')
        r['startup_sent']=True;save();r['events'].append(require(service.program('start',force=True)));monitor()
        near(service.status()['pose_mm'],p['start'],.05)
        from trajectory_queue import LuaTrajectory
        owner=RecoveryService(service,p);s=service.status();run.say('Confirmed empty recovery to HOME at speed5.')
        r['motion_sent']=True;save()
        r['result']=require(LuaTrajectory(owner).execute(run,s['pose_mm'],s['joints'],p['points'],cfg,137,monitor,
            reviewed=True,segment_speeds=p['speeds'],hotel_route='slot1_empty_recovery'))
        monitor();near(service.status()['pose_mm'],p['points'][-1],.05)
        r.update(status='completed_empty_HOME_recovery',final=service.status(),final_native=native(service))
        return dict(ok=True,record=str(path),pose_mm=r['final']['pose_mm'],payload='empty')
    except BaseException as e:
        r.update(status='stopped_or_uncertain',error=str(e))
        if r['startup_sent'] or r['motion_sent']:
            try:r['stop']=service.program('stop')
            except Exception as stop:r['stop_error']=str(stop)
        raise
    finally:r['finished_at']=time.time();save()
