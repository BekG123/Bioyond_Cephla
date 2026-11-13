"""Pinned slot1 recovery: lower50.8mm outside rack, then return beneath slot1."""
import json
import math
import time
from uuid import uuid4
from autonomy import TransferError
from hotel_slot_trial import snapshot,reference,HotelService
from home_hamilton_exchange import native
from plan_hotel_slot1 import SESSION,KEYS
from plan_short_side_hamilton import validate
from scope_step_trial import near
from run_record_io import write_run_record

ANCHOR=dict(X=167.109,Y=-115.001,Z=241.996,Rz=-.839)
OUTPUT=SESSION.parent/'hotel_slot1_loaded_teaching_20261111_222406'/'lower_recovery'


def points_for(start,home):
    low=dict(start,Z=round(start['Z']-50.8,3))
    return [low,dict(low,X=205),dict(X=240.,Y=25.,Z=low['Z'],Rz=.752),home]


def checked(start,points,joints,cfg,envelope,expected):
    near(start,ANCHOR,.05)
    v=validate(start,points,joints,cfg,envelope,expected)
    for item in v['workspace_violations']:
        p=item['pose'];segment=item['segment'];low=start['Z']-50.8
        if set(item['outside'])!={'X'}:raise TransferError('Only pinned X exception allowed.')
        if segment==0:
            near(dict(p,Z=start['Z']),start,.006)
            if not low-.006<=p['Z']<=start['Z']+.006:raise TransferError('Lowering exceeded approved range.')
        elif segment==1:
            near(dict(p,X=start['X'],Z=start['Z']),start,.006)
            if abs(p['Z']-low)>.006 or not start['X']-.006<=p['X']<200:
                raise TransferError('Ingress must follow lowering at the fixed approved height.')
        else:raise TransferError('No later workspace exception allowed.')
    return v


def preview(service,cfg):
    d,digest=reference();s,n=snapshot(service);near(s['pose_mm'],ANCHOR,.05)
    if s['program_state']['state']!='stopped':raise TransferError('Recovery requires the stopped empty-arm state.')
    if cfg!=d['config'] or {k:list(v) for k,v in service.envelope.items()}!=d['envelope']:
        raise TransferError('Recovery geometry/workspace changed.')
    start={k:s['pose_mm'][k] for k in KEYS};points=points_for(start,d['start'])
    checked(start,points,s['joints'],cfg,service.envelope,d['start_joints'])
    return dict(id=uuid4().hex,at=time.time(),start=start,joints=s['joints'],axes=n['external_axes'],
        candidate_sha256=digest,cfg=cfg,envelope=d['envelope'],points=points,speeds=[5]*4,
        workspace_exception='Only vertical50.8 at X167.109 followed by fixed-height X ingress; global envelope unchanged.')


class RecoveryService(HotelService):pass


def prepare_for_service(service,phase,start,joints,points,cfg,envelope,speeds):
    if not isinstance(service,RecoveryService) or phase!='slot1_lower_recovery':raise TransferError('Bound recovery service required.')
    d,digest=reference();p=service.plan
    if cfg!=d['config'] or digest!=p['candidate_sha256'] or {k:list(v) for k,v in envelope.items()}!=d['envelope']:
        raise TransferError('Recovery geometry changed.')
    near(start,p['start'],.05)
    if points!=points_for(p['start'],d['start']) or list(speeds)!=[5]*4:raise TransferError('Exact recovery path/speed required.')
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
            origin=p['start'];low=origin['Z']-50.8
            if pose['X']<origin['X']-.1 or abs(pose['Y']-origin['Y'])>.1 or abs(pose['Rz']-origin['Rz'])>.1:
                raise TransferError('Recovery left the approved outside-workspace line.')
            if abs(pose['X']-origin['X'])<=.1:
                if not low-.1<=pose['Z']<=origin['Z']+.1:raise TransferError('Lowering exceeded approved range.')
            elif abs(pose['Z']-low)>.1:raise TransferError('Horizontal ingress began before approved lowering.')
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
        owner=RecoveryService(service,p);s=service.status();run.say('Lower50.8mm at fixedXY/wrist, then return beneath slot1 to HOME at speed5.')
        r['motion_sent']=True;save()
        r['result']=require(LuaTrajectory(owner).execute(run,s['pose_mm'],s['joints'],p['points'],cfg,137,monitor,
            reviewed=True,segment_speeds=p['speeds'],hotel_route='slot1_lower_recovery'))
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
