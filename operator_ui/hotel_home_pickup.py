"""Accepted 48-well HOME pickup from the confirmed empty teaching start."""
import json
import math
import time
from uuid import uuid4
from autonomy import TransferError
from calibration_e2 import accepted,verify
from projected_pickup import load,accepted_grip
from home_squid_transfer import checked
from home_hamilton_exchange import native
from hotel_slot_trial import reference,snapshot
from hotel_slot2_pickup import state
from scope_step_trial import near
from plan_hotel_slot1 import SESSION,KEYS
from plan_short_side_hamilton import validate
from run_record_io import write_run_record

ANCHOR=dict(X=298.784,Y=4.995,Z=322.818,Rz=19.183)
OUTPUT=SESSION/'loaded_home_pickup'


def geometry(start,joints):
    d,_=reference();p,digest=load();acceptance=accepted_grip(p)
    if not acceptance:raise TransferError('Accepted 48-well pickup required.')
    seat={k:round(p['candidate_endpoint'][k],2) for k in KEYS}
    clear=dict(seat,Z=round(seat['Z']+30,2));proof=dict(seat,Z=round(seat['Z']+5,2))
    routes={
        'home48_connect':dict(start=start,points=[dict(seat,Z=start['Z']),clear],speeds=[40,40],e1=0),
        'home48_descend':dict(start=clear,points=[dict(seat,Z=seat['Z']+20),seat],speeds=[137,5],e1=28),
        'home48_lift':dict(start=seat,points=[proof],speeds=[5],e1=3.9)}
    q=joints
    for r in routes.values():
        q=checked(r['start'],r['points'],q,d['config'],d['envelope'])
        v=validate(r['start'],r['points'],joints if r is routes['home48_connect'] else previous_q,d['config'],d['envelope'],q)
        if not v['workspace_valid']:raise TransferError('HOME pickup exceeds workspace.')
        r['expected']=q;previous_q=q
    return dict(profile=p,profile_sha256=digest,cfg=d['config'],envelope=d['envelope'],routes=routes)


def preview(service,cfg):
    s,n=state(service,0);near(s['pose_mm'],ANCHOR,.05)
    if abs(n['external_axes']['E2']-1.77)>2:raise TransferError('Holder correction exceeds existing bound.')
    g=geometry(ANCHOR,s['joints'])
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:raise TransferError('HOME geometry changed.')
    return dict(id=uuid4().hex,at=time.time(),start=s['pose_mm'],joints=s['joints'],axes=n['external_axes'],geometry=g)


class HomePickupService:
    def __init__(self,owner,plan):self.owner=owner;self.plan=plan;self.expected_e1=0
    def __getattr__(self,name):return getattr(self.owner,name)
    def _preflight(self):
        try:
            state(self.owner,self.expected_e1,False)
            if not accepted(native(self.owner)['external_axes']['E2']):return 'HOME holder angle changed.'
        except Exception as e:return str(e)
        return None


def prepare_for_service(service,phase,start,joints,points,cfg,envelope,speeds):
    if not isinstance(service,HomePickupService):raise TransferError('Bound HOME pickup required.')
    g=service.plan['geometry'];current=geometry(ANCHOR,service.plan['joints'])
    if current!=g or cfg!=g['cfg'] or {k:list(v) for k,v in envelope.items()}!=g['envelope']:raise TransferError('HOME pickup reference changed.')
    if phase not in g['routes']:raise TransferError('Unknown HOME pickup phase.')
    r=g['routes'][phase];near(start,r['start'],.05)
    if points!=r['points'] or list(speeds)!=r['speeds'] or service.expected_e1!=r['e1']:raise TransferError('HOME pickup path/speed/payload changed.')
    out=[{k:math.floor(p[k]*100+.5)/100 for k in KEYS} for p in points]
    v=validate(start,out,joints,cfg,envelope,r['expected'])
    if not v['workspace_valid']:raise TransferError('HOME pickup workspace exceeded.')
    return out,v['endpoint_joints']


def execute(run,service,cfg,approved,gripper):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('HOME pickup preview expired.')
    p=preview(service,cfg);near(p['start'],approved['start'],.05)
    if p['geometry']['profile_sha256']!=approved['geometry']['profile_sha256'] or any(abs(p['joints'][k]-approved['joints'][k])>.1 for k in p['joints']) or any(abs(p['axes'][k]-approved['axes'][k])>.1 for k in ('E1','E2')):raise TransferError('HOME pickup start/reference changed.')
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/(p['id']+'.json')
    r=dict(status='starting',at=time.time(),plan=p,steps=[],samples=[],motion_sent=False,automatic_retries=False,
        plate_setup_and_route_confirmed=True)
    expected=0;holder_required=False;owner=HomePickupService(service,p)
    def save():write_run_record(path,r)
    def require(v):
        if not v.get('ok') or v.get('recovered') or v.get('gripper_warning'):raise TransferError('HOME pickup failed/uncertain; no retry: '+str(v))
        return v
    def monitor(*args):
        if run.stopped():raise TransferError('HOME pickup stopped.')
        s,n=state(service,expected,False)
        if holder_required and not accepted(n['external_axes']['E2']):raise TransferError('Holder changed during pickup.')
        r['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
    def queue(phase):
        from trajectory_queue import LuaTrajectory
        monitor();s,_=state(service,expected);route=p['geometry']['routes'][phase];owner.expected_e1=expected
        run.say(phase);r['motion_sent']=True;save()
        result=require(LuaTrajectory(owner).execute(run,s['pose_mm'],s['joints'],route['points'],cfg,137,monitor,
            reviewed=True,segment_speeds=route['speeds'],hotel_route=phase))
        r['steps'].append(dict(phase=phase,result=result));save();monitor();near(service.status()['pose_mm'],route['points'][-1],.05)
    save()
    try:
        monitor();run.say('Restore holder to1.77 with empty jaws and arm above the fixture.')
        r['motion_sent']=True;save();r['holder_readings']=verify(service,run,correct=True);holder_required=True;save()
        near(service.status()['pose_mm'],p['start'],.05)
        queue('home48_connect')
        monitor();before=service.status()['pose_mm'];r['steps'].append(dict(phase='open28',status='dispatching'));save()
        r['steps'][-1]['result']=require(service.move_gripper(28,5));expected=28;monitor();near(service.status()['pose_mm'],before,.05)
        queue('home48_descend')
        g=p['geometry'];context=dict(plate_profile_id=g['profile']['id'],descent_correction=dict(endpoint=g['profile']['candidate_endpoint'],profile_sha256=g['profile_sha256']))
        ref,digest=gripper._configuration(context)
        receipt=dict(pose_mm=service.status()['pose_mm'],descent_result=context,grip_reference_sha256=digest,hotel_home_trial=str(path))
        r['descent_receipt']=receipt;save();run.say('Accepted 48-well long-side grip3.9.')
        result=require(gripper.execute(run,receipt));r['steps'].append(dict(phase='accepted_grip',result=result));expected=3.9;monitor()
        queue('home48_lift');s,n=state(service,3.9)
        r.update(status='HOME_plate_lifted_for_teaching_retention_pending',final=s,final_native=n)
        return dict(ok=True,record=str(path),pose_mm=s['pose_mm'],payload='held_pending_inspection')
    except BaseException as e:
        r.update(status='stopped_or_uncertain',error=str(e))
        if r['motion_sent']:
            try:r['stop']=service.program('stop')
            except Exception as stop:r['stop_error']=str(stop)
        raise
    finally:r['finished_at']=time.time();save()
