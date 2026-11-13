"""Accepted slot1 approach with first supervised5mm pickup and speed137 travel."""
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
from hotel_home_start import check_home_start

PREFIX='slot1_retrieval_'
SOURCE=FOLDER/'deliveries/c29d5b8024a74fefb209b59b6e2274e8.json'
ACCEPTANCE=SOURCE.with_name(SOURCE.stem+'_operator_acceptance.json')
OUTPUT=FOLDER/'retrievals'


def checked(start,points,joints,cfg,env,outside=False):
    q=dict(joints);old=start;offset=q['J1']-start['Z']
    for p in points:
        q=check_path(old,p,q,cfg,None);q['J1']=p['Z']+offset;old=p
    v=validate(start,points,joints,cfg,env,q)
    for item in v['workspace_violations']:
        p=item['pose']
        if (not outside or set(item['outside'])!={'X'} or not OUTSIDE_X-.009<=p['X']<200 or
            not -139.42<=p['Y']<=-114.99 or not 191.19<=p['Z']<=245.61 or abs(p['Rz']-.752)>.01):
            raise TransferError('Outside the exact slot1 retrieval corridor.')
    return v


def geometry():
    d=delivery_geometry();raw=SOURCE.read_bytes();source=json.loads(raw);approval=json.loads(ACCEPTANCE.read_bytes())
    digest=hashlib.sha256(raw).hexdigest()
    if (source['status']!='completed_delivery_empty_HOME_operator_observation_pending' or
        source['plan']['geometry']!=delivery_geometry(revision=2) or approval['source_sha256']!=digest or
        json.loads(CORRECTION.read_bytes()).get('parent_delivery_sha256')!=digest or
        approval.get('plate_flat_and_secure_in_slot1') is not True):
        raise TransferError('Accepted baseline and explicit slot1 correction required.')
    home=d['home'];approach=d['routes']['deliver']['points'][1:];end=approach[-1]
    lift=dict(end,Z=round(end['Z']+5,3))
    reverse=[dict(d['routes']['return']['points'][0],Z=lift['Z'])]+d['routes']['return']['points'][1:]
    pickup=d['routes']['descend']['points'][-1];seat=seating_plan(pickup)['pose']
    clear=d['routes']['connect']['points'][-1]
    routes={
        'approach':dict(start=home,points=approach,speeds=[137,137,137,137,137,20],e1=7),
        'lift':dict(start=end,points=[lift],speeds=[5],e1=3.9),
        'return':dict(start=lift,points=reverse,speeds=[20,137,137,137,137,137],e1=3.9),
        'seat':dict(start=home,points=[dict(seat,Z=home['Z']),seat],speeds=[5,5],e1=3.9),
        'clear':dict(start=seat,points=[clear,home],speeds=[137,137],e1=28)}
    base,_=reference();q=base['start_joints']
    for name,r in routes.items():
        v=checked(r['start'],r['points'],q,d['cfg'],d['envelope'],name in ('approach','return'))
        q=v['endpoint_joints'];r['expected']=q
    return dict(delivery_geometry=d,source_sha256=digest,acceptance_sha256=hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest(),
                cfg=d['cfg'],envelope=d['envelope'],home=home,routes=routes,lift_mm=5,release_at_HOME=28)


def preview(service,cfg):
    s,n=state(service,7);g=geometry();check_home_start(s['pose_mm'],g['home'])
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:raise TransferError('Geometry changed.')
    if not accepted(n['external_axes']['E2']):raise TransferError('HOME holder must remain in its original accepted orientation.')
    # Check the actual approach, not a substituted nominal HOME coordinate.
    r=g['routes']['approach']
    v=checked(s['pose_mm'],r['points'],s['joints'],cfg,service.envelope,True)
    if max(abs(v['endpoint_joints'][k]-r['expected'][k]) for k in r['expected'])>.5:
        raise TransferError('Retrieval winding changed.')
    return dict(id=uuid4().hex,at=time.time(),start=s['pose_mm'],joints=s['joints'],axes=n['external_axes'],geometry=g)


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
    r=g['routes'][name]
    if name=='approach':
        check_home_start(start,r['start'])
        near(start,service.plan['start'],.05)
    else:near(start,r['start'],.05)
    if points!=r['points'] or list(speeds)!=r['speeds'] or service.expected_e1!=r['e1']:raise TransferError('Route, speed or grip changed.')
    out=[{k:math.floor(p[k]*100+.5)/100 for k in KEYS} for p in points]
    v=checked(start,out,joints,cfg,envelope,name in ('approach','return'))
    if max(abs(v['endpoint_joints'][k]-r['expected'][k]) for k in r['expected'])>.5:raise TransferError('Retrieval winding changed.')
    return out,v['endpoint_joints']


def settle_released_holder(run,service,cfg,g,record,save):
    """Finish the scanner handoff postcondition after release and clearance.

    Correct contact deflection once, never retry a failed command. This is
    called only by the composed transfer that includes this preparation.
    """
    from cellvis_recovery_handoff import restore_segments
    def check(expected=None):
        if run.stopped():raise TransferError('Stopped before scanner holder preparation.')
        s,n=state(service,28);axes=n['external_axes']
        near(s['pose_mm'],g['home'],.05)
        if cfg!=g['cfg'] or not service.envelope_enabled or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
            raise TransferError('Scanner holder preparation configuration changed.')
        if abs(axes['E1']-28)>.07:raise TransferError('Scanner holder preparation requires released jaws at 28 mm.')
        if abs(axes['E2']-1.77)>HOLDER_MONITOR_TOLERANCE_DEG:
            raise TransferError('Released holder exceeds the accepted contact-deflection bound; no correction.')
        if expected is not None and abs(axes['E2']-expected)>.1:
            raise TransferError('Holder changed or correction arrival mismatch; no retry.')
        return s,n
    def require(result):
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
            raise TransferError('Holder correction failed or uncertain; no retry: '+str(result))
        return result
    item=dict(phase='scanner_holder_preparation',status='checking',samples=[],correction_sent=False)
    record['steps'].append(item);save()
    stable=0
    for _ in range(3):
        s,n=check();angle=n['external_axes']['E2']
        item['samples'].append(angle);save()
        stable=stable+1 if accepted(angle) else 0
        time.sleep(.1)
    if stable!=3:
        origin=n['external_axes']['E2']
        def dispatch():
            item['correction_sent']=True;record['motion_sent']=True;save()
        def segment(value):item['correction']=value;save()
        run.say('Plate released and arm clear: restore holder to 1.77 degrees before scanning.')
        restore_segments(run,service,[1.77],origin,check,require,dispatch,segment)
        for _ in range(3):
            s,n=check(1.77);item['samples'].append(n['external_axes']['E2']);save()
            if not accepted(n['external_axes']['E2']):
                raise TransferError('Scanner holder angle not verified after correction; no retry.')
            time.sleep(.1)
    item['status']='completed';save()


def execute(run,service,cfg,approved,*,restore_holder_for_handoff=False):
    if type(restore_holder_for_handoff) is not bool:raise TransferError('Invalid holder handoff preparation option.')
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Preview expired.')
    p=preview(service,cfg);near(p['start'],approved['start'],.05)
    if p['geometry']!=approved['geometry'] or any(abs(p['axes'][k]-approved['axes'][k])>.1 for k in ('E1','E2')):
        raise TransferError('Retrieval setup changed.')
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/(p['id']+'.json')
    record=dict(at=time.time(),status='starting',plan=p,steps=[],samples=[],motion_sent=False,automatic_retries=False,
                restore_holder_for_handoff=restore_holder_for_handoff)
    expected=7;holder_required=False;owner=RetrievalService(service,p)
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
        run.say('Slot1 retrieval: '+name);record['motion_sent']=True;save()
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
        queue('approach')
        for command in closure_commands(7,3.9):jaw(command['target_e1_mm'],command['speed'])
        queue('lift');queue('return')
        # Preserve the stationary orientation gate before seating, then use
        # the established holder-exchange motion tolerance during contact.
        _,arrival=state(service,expected)
        if not accepted(arrival['external_axes']['E2']):raise TransferError('HOME holder angle changed before seating.')
        holder_required=True
        queue('seat');jaw(28,5);queue('clear')
        if restore_holder_for_handoff:settle_released_holder(run,service,cfg,p['geometry'],record,save)
        s,n=state(service,28);record.update(status='completed_retrieval_HOME_released_operator_observation_pending',final=s,final_native=n)
        if restore_holder_for_handoff and not accepted(n['external_axes']['E2']):
            raise TransferError('Holder changed after scanner preparation; no handoff.')
        return dict(ok=True,record=str(path),pose_mm=s['pose_mm'],payload='empty',plate_location='HOME_release_completed_pending_visual_confirmation')
    except BaseException as e:
        record.update(status='stopped_or_uncertain',error=str(e))
        if record['motion_sent']:
            try:record['stop']=service.program('stop')
            except Exception as stop:record['stop_error']=str(stop)
        raise
    finally:record['finished_at']=time.time();save()
