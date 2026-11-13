"""48-well HOME pickup, lower-corridor slot1 delivery and empty return.

No calibration, fault clearing, controller startup, automatic retry or slot offsets.
"""
import hashlib
import json
import math
import time
from uuid import uuid4
from pathlib import Path
from autonomy import TransferError, check_path
from calibration_e2 import accepted, verify
from hotel_slot_trial import reference
from hotel_slot2_pickup import state
from home_hamilton_exchange import native
from projected_pickup import load, accepted_grip
from plan_short_side_hamilton import validate
from scope_step_trial import near
from run_record_io import write_run_record

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'operator_ui/reports/plate_session/hotel_slot1_loaded_teaching_20261111_222406'
OUTPUT=FOLDER/'deliveries'
KEYS=('X','Y','Z','Rz')
PREFIX='slot1_delivery_'
OUTSIDE_X=154.409
CORRECTION=FOLDER/'slot1_approach_revision3.json'
RETURN_CORRECTION=FOLDER/'slot1_return_speed_revision4.json'
HORIZONTAL_CORRECTION=FOLDER/'slot1_horizontal_speed_revision5.json'
SOURCES=[FOLDER/'slot_1_loaded_endpoint_capture.json',
         FOLDER/'lower_recovery/77e9989b2e904acda6ec27fac3312ce3.json',
         FOLDER/'slot1_loaded_clearance_revision2.json']


def sources():
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES}


def check_geometry(start,points,joints,cfg,env,allow_outside=False):
    q=dict(joints);previous=start;offset=q['J1']-start['Z']
    for point in points:
        q=check_path(previous,point,q,cfg,None);q['J1']=point['Z']+offset;previous=point
    v=validate(start,points,joints,cfg,env,q)
    for item in v['workspace_violations']:
        p=item['pose']
        if (not allow_outside or set(item['outside'])!={'X'} or
                not OUTSIDE_X-.009<=p['X']<200 or not -139.42<=p['Y']<=-114.99 or
                not 191.19<=p['Z']<=240.61 or abs(p['Rz']-.752)>.01):
            raise TransferError('Outside the exact lower rack corridor.')
    return v


def geometry(revision=5):
    if revision not in (2,3,4,5):raise TransferError('Unknown slot1 revision.')
    base,digest=reference();profile,sha=load()
    if not accepted_grip(profile):raise TransferError('Accepted48-well pickup required.')
    capture=json.loads(SOURCES[0].read_bytes());recovery=json.loads(SOURCES[1].read_bytes())
    if recovery['status']!='completed_empty_HOME_recovery':raise TransferError('Completed lower recovery required.')
    clearance=json.loads(SOURCES[2].read_bytes())
    if clearance['outside_x_mm']!=OUTSIDE_X or clearance['offset_mm']!=-12.7:raise TransferError('Outside correction changed.')
    home=base['start'];seat={k:round(profile['candidate_endpoint'][k],2) for k in KEYS}
    clear=dict(seat,Z=round(seat['Z']+30,2));proof=dict(seat,Z=round(seat['Z']+5,2))
    end={k:capture['state']['robot']['pose_mm'][k] for k in KEYS}
    taught=dict(end);hashes=sources()
    if revision>=3:
        correction=json.loads(CORRECTION.read_bytes())
        if any(correction.get(k)!=v for k,v in dict(revision=3,insertion_delta_x_mm=-6.35,
                original_endpoint_x_mm=297.228,endpoint_x_mm=290.878,outside_z_speed=137,
                horizontal_entry_speed=10,proof_lift_mm=5,proof_lift_speed=5).items()):
            raise TransferError('Slot1 insertion correction changed.')
        if taught['X']!=correction['original_endpoint_x_mm']:raise TransferError('Original insertion reference changed.')
        end=dict(end,X=round(end['X']+correction['insertion_delta_x_mm'],3))
        hashes[str(CORRECTION)]=hashlib.sha256(CORRECTION.read_bytes()).hexdigest()
    if revision>=4:
        return_correction=json.loads(RETURN_CORRECTION.read_bytes())
        if any(return_correction.get(k)!=v for k,v in dict(revision=4,horizontal_withdrawal_speed=5,
                outside_descent_and_home_return_speed=137,parent_approach_sha256=hashes[str(CORRECTION)]).items()):
            raise TransferError('Slot1 return-speed correction changed.')
        hashes[str(RETURN_CORRECTION)]=hashlib.sha256(RETURN_CORRECTION.read_bytes()).hexdigest()
    if revision==5:
        horizontal=json.loads(HORIZONTAL_CORRECTION.read_bytes())
        if any(horizontal.get(k)!=v for k,v in dict(revision=5,horizontal_entry_speed=20,
                horizontal_withdrawal_speed=20,parent_return_sha256=hashes[str(RETURN_CORRECTION)]).items()):
            raise TransferError('Slot1 horizontal-speed correction changed.')
        hashes[str(HORIZONTAL_CORRECTION)]=hashlib.sha256(HORIZONTAL_CORRECTION.read_bytes()).hexdigest()
    pivot=dict(X=240.,Y=25.,Z=191.196,Rz=end['Rz'])
    inside=dict(X=205.,Y=-115.001,Z=191.196,Rz=end['Rz'])
    outside=dict(inside,X=OUTSIDE_X)
    low=dict(outside,Y=end['Y']);high=dict(low,Z=end['Z'])
    forward=[home,pivot,inside,outside,low,high,end]
    back=[high,low,outside,inside,pivot,home]
    routes={
        'connect':dict(start=home,points=[clear],speeds=[5],e1=0),
        'descend':dict(start=clear,points=[dict(seat,Z=seat['Z']+20),seat],speeds=[137,5],e1=28),
        'proof':dict(start=seat,points=[proof],speeds=[5],e1=3.9),
        'deliver':dict(start=proof,points=forward,speeds=([137]*6+[20 if revision==5 else 10] if revision>=3 else [5]*len(forward)),e1=3.9),
        'return':dict(start=end,points=back,speeds=([20 if revision==5 else 5]+[137]*5 if revision>=4 else [5]*len(back)),e1=7)}
    q=base['start_joints']
    for name,r in routes.items():
        v=check_geometry(r['start'],r['points'],q,base['config'],base['envelope'],name in ('deliver','return'))
        q=v['endpoint_joints'];r['expected']=q
        if name=='deliver':
            taught_q=capture['state']['robot']['joints']
            expected=taught_q if revision==2 else check_path(taught,end,taught_q,base['config'],None)
            if max(abs(q[k]-expected[k]) for k in q)>.5:
                raise TransferError('Loaded endpoint winding differs from taught branch.')
    if max(abs(q[k]-base['start_joints'][k]) for k in q)>.5:raise TransferError('Return winding changed.')
    assert high['Y']==end['Y'] and high['Z']==end['Z'] and high['Rz']==end['Rz']
    return dict(cfg=base['config'],envelope=base['envelope'],routes=routes,profile=profile,
                profile_sha256=sha,source_hashes=hashes,parent_sha256=digest,
                pickup=3.9,release=7,home=home)


def preview(service,cfg):
    s,n=state(service,0);g=geometry();near(s['pose_mm'],g['home'],.05)
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
        raise TransferError('Configuration changed.')
    if abs(n['external_axes']['E2']-1.77)>2:raise TransferError('Holder outside correction bound.')
    return dict(id=uuid4().hex,at=time.time(),start=s['pose_mm'],joints=s['joints'],axes=n['external_axes'],geometry=g)


class DeliveryService:
    def __init__(self,owner,plan):self.owner=owner;self.plan=plan;self.expected_e1=0
    def __getattr__(self,name):return getattr(self.owner,name)
    def _preflight(self):
        try:state(self.owner,self.expected_e1,False)
        except Exception as e:return str(e)
        return None


def prepare_for_service(service,phase,start,joints,points,cfg,envelope,speeds):
    if not isinstance(service,DeliveryService) or not phase.startswith(PREFIX):
        raise TransferError('Bound delivery service required.')
    name=phase[len(PREFIX):];g=service.plan['geometry']
    if g!=geometry() or cfg!=g['cfg'] or {k:list(v) for k,v in envelope.items()}!=g['envelope']:
        raise TransferError('Delivery evidence changed.')
    if name not in g['routes']:raise TransferError('Unknown phase.')
    r=g['routes'][name];near(start,r['start'],.05)
    if points!=r['points'] or list(speeds)!=r['speeds'] or service.expected_e1!=r['e1']:
        raise TransferError('Route, payload or speed changed.')
    out=[{k:math.floor(p[k]*100+.5)/100 for k in KEYS} for p in points]
    v=check_geometry(start,out,joints,cfg,envelope,name in ('deliver','return'))
    if max(abs(v['endpoint_joints'][k]-r['expected'][k]) for k in r['expected'])>.5:
        raise TransferError('Live winding changed.')
    return out,v['endpoint_joints']


def execute(run,service,cfg,approved,gripper,*,pickup_only=False):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Preview expired.')
    p=preview(service,cfg);near(p['start'],approved['start'],.05)
    if p['geometry']!=approved['geometry'] or any(abs(p['axes'][k]-approved['axes'][k])>.1 for k in ('E1','E2')):
        raise TransferError('Setup changed after preview.')
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/(p['id']+'.json')
    r=dict(at=time.time(),status='starting',plan=p,steps=[],samples=[],motion_sent=False,automatic_retries=False,pickup_only=pickup_only)
    expected=0;holder_required=False;owner=DeliveryService(service,p)
    def save():write_run_record(path,r)
    def require(v):
        if not v.get('ok') or v.get('recovered') or v.get('gripper_warning'):
            raise TransferError('Failed/uncertain delivery step; no retry: '+str(v))
        return v
    def monitor(*args):
        if run.stopped():raise TransferError('Delivery stopped.')
        s,n=state(service,expected,False)
        r['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
        if holder_required and not accepted(n['external_axes']['E2']):
            raise TransferError(f"Holder changed before grip verification: E2={n['external_axes']['E2']:.6f} degrees.")
    def queue(name):
        from trajectory_queue import LuaTrajectory
        monitor();s,_=state(service,expected);route=p['geometry']['routes'][name];owner.expected_e1=expected
        run.say('Slot1: '+name);r['motion_sent']=True;save()
        result=require(LuaTrajectory(owner).execute(run,s['pose_mm'],s['joints'],route['points'],cfg,137,monitor,
                    reviewed=True,segment_speeds=route['speeds'],hotel_route=PREFIX+name))
        r['steps'].append(dict(phase=name,result=result));save();monitor();near(service.status()['pose_mm'],route['points'][-1],.05)
    def opening(target):
        nonlocal expected
        monitor();before=service.status()['pose_mm'];r['motion_sent']=True
        item=dict(phase='open',target=target,status='dispatching');r['steps'].append(item);save()
        item.update(result=require(service.move_gripper(target,5)),status='completed');expected=target
        monitor();near(service.status()['pose_mm'],before,.05)
    save()
    try:
        monitor();r['motion_sent']=True;save();r['holder_readings']=verify(service,run,correct=True);holder_required=True
        queue('connect');opening(28);queue('descend')
        g=p['geometry'];context=dict(plate_profile_id=g['profile']['id'],descent_correction=dict(endpoint=g['profile']['candidate_endpoint'],profile_sha256=g['profile_sha256']))
        _,digest=gripper._configuration(context)
        receipt=dict(pose_mm=service.status()['pose_mm'],descent_result=context,grip_reference_sha256=digest,hotel_delivery=str(path))
        r['descent_receipt']=receipt;save()
        result=require(gripper.execute(run,receipt));r['steps'].append(dict(phase='grip3.9',result=result));expected=3.9;monitor()
        # Match the accepted HOME/Squid pickup: verify the holder through the
        # stationary grip, then stop applying its seating gate during lift.
        holder_required=False;queue('proof')
        if pickup_only:
            s,n=state(service,3.9)
            r.update(status='HOME_plate_lifted_for_teaching_retention_pending',final=s,final_native=n)
            return dict(ok=True,record=str(path),pose_mm=s['pose_mm'],payload='held_pending_inspection',rack_motion_started=False)
        queue('deliver');opening(7);queue('return')
        s,n=state(service,7);r.update(status='completed_delivery_empty_HOME_operator_observation_pending',final=s,final_native=n)
        return dict(ok=True,record=str(path),pose_mm=s['pose_mm'],payload='empty',plate_location='slot1_release_completed_pending_visual_confirmation')
    except BaseException as e:
        r.update(status='stopped_or_uncertain',error=str(e))
        if r['motion_sent']:
            try:r['stop']=service.program('stop')
            except Exception as stop:r['stop_error']=str(stop)
        raise
    finally:r['finished_at']=time.time();save()
