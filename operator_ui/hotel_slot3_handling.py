"""Taught slot3 release/empty return and retrieval; never restart or retry."""
import hashlib
import json
import math
import time
from uuid import uuid4
from autonomy import TransferError,check_path
from calibration_e2 import accepted
from hotel_slot1_delivery import FOLDER,KEYS,OUTSIDE_X,CORRECTION,geometry as delivery_geometry
from hotel_slot_trial import reference
from hotel_slot2_pickup import state
from plan_short_side_hamilton import validate
from scope_step_trial import near
from home_seating import seating_plan
from gripper_closure import closure_commands
from run_record_io import write_run_record
from home_hamilton_exchange import HOLDER_MONITOR_TOLERANCE_DEG

PREFIX='slot3_handling_'
from plan_hotel_slot2_from_slot1 import CAPTURE,build
from hotel_slot2_trial import geometry as approach_geometry
SOURCE=CAPTURE.parent/'slot3_successful_approach_reference.json'
OUTPUT=CAPTURE.parent/'handling_trials'


def checked(start,points,joints,cfg,env,outside=False):
    q=dict(joints);old=start;offset=q['J1']-start['Z']
    for p in points:
        q=check_path(old,p,q,cfg,None);q['J1']=p['Z']+offset;old=p
    v=validate(start,points,joints,cfg,env,q)
    for item in v['workspace_violations']:
        p=item['pose']
        if (not outside or set(item['outside'])!={'X'} or not OUTSIDE_X-.009<=p['X']<200 or
            not -139.43<=p['Y']<=-114.98 or not 191.186<=p['Z']<=357.42 or not -.662<=p['Rz']<=.762):
            raise TransferError('Outside the exact taught slot3 handling corridor.')
    return v


def geometry():
    binding=json.loads(SOURCE.read_bytes());raw=(CAPTURE.parent/binding['record']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=binding['sha256']:raise TransferError('Slot3 approach receipt changed.')
    source=json.loads(raw);a=approach_geometry(3)
    if (source['status']!='arrived_slot3_held_support_inspection_pending' or
            source['plan']['geometry']!=a or source.get('release_sent') is not False):
        raise TransferError('Completed taught slot3 approach required.')
    d=build(3)
    if d['blockers']:raise TransferError('Slot3 geometry is blocked.')
    routes=d['retrieval_routes']
    routes['empty_return']=d['delivery_routes']['return']
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(),approach_geometry=a,
        cfg=a['cfg'],envelope=a['envelope'],home=routes['approach']['start'],routes=routes,
        lift_mm=5,release_at_slot=7,release_at_HOME=28)


def preview(service,cfg,action='retrieve'):
    if action not in ('release_return','retrieve'):raise TransferError('Unknown slot3 handling action.')
    expected=3.9 if action=='release_return' else 7
    s,n=state(service,expected);g=geometry()
    start=g['routes']['empty_return']['start'] if action=='release_return' else g['home']
    near(s['pose_mm'],start,.05)
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:raise TransferError('Geometry changed.')
    if not accepted(n['external_axes']['E2']):raise TransferError('HOME holder must remain in its original accepted orientation.')
    return dict(id=uuid4().hex,at=time.time(),action=action,start=s['pose_mm'],joints=s['joints'],axes=n['external_axes'],geometry=g)


class RetrievalService:
    def __init__(self,owner,plan):self.owner=owner;self.plan=plan;self.expected_e1=7
    def __getattr__(self,name):return getattr(self.owner,name)
    def _preflight(self):
        try:state(self.owner,self.expected_e1,False)
        except Exception as e:return str(e)
        return None


def prepare_for_service(service,phase,start,joints,points,cfg,envelope,speeds):
    if not isinstance(service,RetrievalService) or not phase.startswith(PREFIX):raise TransferError('Bound retrieval required.')
    g=service.plan['geometry'];name=phase[len(PREFIX):]
    if g!=geometry() or cfg!=g['cfg'] or {k:list(v) for k,v in envelope.items()}!=g['envelope']:raise TransferError('Retrieval reference changed.')
    if name not in g['routes']:raise TransferError('Unknown retrieval phase.')
    r=g['routes'][name];near(start,r['start'],.05)
    if points!=r['points'] or list(speeds)!=r['speeds'] or service.expected_e1!=r['e1']:raise TransferError('Route, speed or grip changed.')
    out=[{k:math.floor(p[k]*100+.5)/100 for k in KEYS} for p in points]
    v=checked(start,out,joints,cfg,envelope,name in ('approach','return','empty_return'))
    if max(abs(v['endpoint_joints'][k]-r['expected'][k]) for k in r['expected'])>.5:raise TransferError('Retrieval winding changed.')
    return out,v['endpoint_joints']


def execute(run,service,cfg,approved):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Preview expired.')
    p=preview(service,cfg,approved['action']);near(p['start'],approved['start'],.05)
    if p['geometry']!=approved['geometry'] or any(abs(p['axes'][k]-approved['axes'][k])>.1 for k in ('E1','E2')):
        raise TransferError('Retrieval setup changed.')
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/(p['id']+'.json')
    record=dict(at=time.time(),status='starting',plan=p,steps=[],samples=[],motion_sent=False,automatic_retries=False)
    expected=3.9 if p['action']=='release_return' else 7;holder_required=False;owner=RetrievalService(service,p)
    def save():write_run_record(path,record)
    def require(v):
        if not v.get('ok') or v.get('recovered') or v.get('gripper_warning'):raise TransferError('Retrieval failed/uncertain; no retry: '+str(v))
        return v
    def monitor(*args):
        if run.stopped():raise TransferError('Retrieval stopped.')
        s,n=state(service,expected,False)
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
        if holder_required and abs(n['external_axes']['E2']-1.77)>HOLDER_MONITOR_TOLERANCE_DEG:
            raise TransferError(f"HOME holder angle changed during seating: E2={n['external_axes']['E2']:.6f}, target1.77, tolerance{HOLDER_MONITOR_TOLERANCE_DEG} degrees.")
    def queue(name):
        from trajectory_queue import LuaTrajectory
        monitor();s,_=state(service,expected);r=p['geometry']['routes'][name];owner.expected_e1=expected
        run.say('Slot3 handling: '+name);record['motion_sent']=True;save()
        result=require(LuaTrajectory(owner).execute(run,s['pose_mm'],s['joints'],r['points'],cfg,137,monitor,
            reviewed=True,segment_speeds=r['speeds'],hotel_route=PREFIX+name))
        record['steps'].append(dict(phase=name,result=result));save();monitor();near(service.status()['pose_mm'],r['points'][-1],.05)
    def jaw(target,speed):
        nonlocal expected
        monitor();before=service.status()['pose_mm'];record['motion_sent']=True
        item=dict(phase='jaw',target=target,speed=speed,status='dispatching');record['steps'].append(item);save()
        item.update(result=require(service.move_gripper(target,speed)),status='completed');expected=target
        monitor();near(service.status()['pose_mm'],before,.05)
    save()
    try:
        if p['action']=='release_return':
            jaw(7,5);queue('empty_return')
            s,n=state(service,7)
            record.update(status='completed_slot3_release_empty_HOME_operator_observation_pending',final=s,final_native=n)
            return dict(ok=True,record=str(path),pose_mm=s['pose_mm'],payload='empty',plate_location='slot3')
        queue('approach')
        for command in closure_commands(7,3.9):jaw(command['target_e1_mm'],command['speed'])
        queue('lift');queue('return')
        # Preserve the stationary orientation gate before seating, then use
        # the established holder-exchange motion tolerance during contact.
        _,arrival=state(service,expected)
        if not accepted(arrival['external_axes']['E2']):raise TransferError('HOME holder angle changed before seating.')
        holder_required=True
        queue('seat');jaw(28,5);queue('clear')
        s,n=state(service,28);record.update(status='completed_retrieval_HOME_released_operator_observation_pending',final=s,final_native=n)
        return dict(ok=True,record=str(path),pose_mm=s['pose_mm'],payload='empty',plate_location='HOME_release_completed_pending_visual_confirmation')
    except BaseException as e:
        record.update(status='stopped_or_uncertain',error=str(e))
        if record['motion_sent']:
            try:record['stop']=service.program('stop')
            except Exception as stop:record['stop_error']=str(stop)
        raise
    finally:record['finished_at']=time.time();save()
