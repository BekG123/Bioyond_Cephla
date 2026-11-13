"""Bound first loaded slot2 approach; stop held, no release or retry."""
import hashlib
import json
import math
import time
from uuid import uuid4
from autonomy import TransferError,check_path
from plan_hotel_slot2_from_slot1 import CAPTURE,ROOT,build
from hotel_slot_trial import reference
from hotel_slot2_pickup import state
from scope_step_trial import near
from plan_short_side_hamilton import validate
from run_record_io import write_run_record

PLAN=CAPTURE.parent/'slot2_candidate_v1.json'
OUTPUT=CAPTURE.parent/'loaded_trials'
PHASE='slot2_taught_approach'
KEYS=('X','Y','Z','Rz')

def geometry(slot=2):
    if slot not in (2,3):raise TransferError('Only slots2/3 are enabled for supervised approach trials.')
    plan_path=CAPTURE.parent/f'slot{slot}_candidate_v1.json'
    if slot==3 and (CAPTURE.parent/'slot3_height_correction_v2.json').exists():
        plan_path=CAPTURE.parent/'slot3_candidate_v2.json'
    raw=plan_path.read_bytes();saved=json.loads(raw);fresh=build(slot)
    if fresh['blockers'] or saved['capture_sha256']!=fresh['capture_sha256'] or saved['delivery_routes']!=fresh['delivery_routes']:
        raise TransferError('Slot2 candidate changed or blocked.')
    base,_=reference()
    return dict(slot=slot,candidate_sha256=hashlib.sha256(raw).hexdigest(),capture_sha256=fresh['capture_sha256'],
        cfg=base['config'],envelope=base['envelope'],route=saved['delivery_routes']['deliver'],
        start_joints=saved['delivery_routes']['proof']['expected'],endpoint=fresh['endpoint'])

def checked(start,points,joints,g):
    q=dict(joints);previous=start;offset=q['J1']-start['Z']
    for p in points:
        q=check_path(previous,p,q,g['cfg'],None);q['J1']=p['Z']+offset;previous=p
    v=validate(start,points,joints,g['cfg'],g['envelope'],q)
    for issue in v['workspace_violations']:
        p=issue['pose']
        if (set(issue['outside'])!={'X'} or not 154.399<=p['X']<200 or not -139.43<=p['Y']<=-114.98 or
                not 191.186<=p['Z']<=min(400,g['endpoint']['Z']+.02) or not -.662<=p['Rz']<=.762):
            raise TransferError('Outside the exact taught slot2 corridor.')
    if max(abs(v['endpoint_joints'][k]-g['route']['expected'][k]) for k in q)>.5:
        raise TransferError('Slot2 winding changed.')
    return v

def preview(service,cfg,slot=2):
    s,n=state(service,3.9);g=geometry(slot);near(s['pose_mm'],g['route']['start'],.05)
    if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:raise TransferError('Slot2 configuration changed.')
    checked(s['pose_mm'],g['route']['points'],s['joints'],g)
    return dict(id=uuid4().hex,at=time.time(),start=s['pose_mm'],joints=s['joints'],geometry=g,axes=n['external_axes'])

class TrialService:
    def __init__(self,owner,plan):self.owner=owner;self.plan=plan
    def __getattr__(self,name):return getattr(self.owner,name)
    def _preflight(self):
        try:state(self.owner,3.9,False)
        except Exception as e:return str(e)
        return None

def prepare_for_service(service,phase,start,joints,points,cfg,envelope,speeds):
    if not isinstance(service,TrialService):raise TransferError('Bound taught hotel trial required.')
    g=service.plan['geometry'];r=g['route']
    if phase!=f"slot{g['slot']}_taught_approach":raise TransferError('Slot and phase mismatch.')
    if g!=geometry(g['slot']) or cfg!=g['cfg'] or {k:list(v) for k,v in envelope.items()}!=g['envelope']:raise TransferError('Hotel evidence changed.')
    near(start,r['start'],.05)
    if points!=r['points'] or list(speeds)!=r['speeds']:raise TransferError('Slot2 route or speed changed.')
    out=[{k:math.floor(p[k]*100+.5)/100 for k in KEYS} for p in points]
    return out,checked(start,out,joints,g)['endpoint_joints']

def execute(run,service,cfg,approved):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Slot2 preview expired.')
    slot=approved['geometry']['slot'];p=preview(service,cfg,slot);near(p['start'],approved['start'],.05)
    if p['geometry']!=approved['geometry']:raise TransferError('Slot2 plan changed.')
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/(p['id']+'.json')
    record=dict(at=time.time(),status='starting',plan=p,samples=[],motion_sent=False,release_sent=False,automatic_retries=False)
    def save():write_run_record(path,record)
    def monitor(*args):
        if run.stopped():raise TransferError('Slot2 trial stopped.')
        s,n=state(service,3.9,False);record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
    save()
    try:
        from trajectory_queue import LuaTrajectory
        monitor();record['motion_sent']=True;save();r=p['geometry']['route']
        result=LuaTrajectory(TrialService(service,p)).execute(run,p['start'],p['joints'],r['points'],cfg,137,monitor,
            reviewed=True,segment_speeds=r['speeds'],hotel_route=f'slot{slot}_taught_approach')
        record['result']=result
        if not result.get('ok') or result.get('recovered'):raise TransferError('Slot2 trial failed or uncertain; no retry.')
        s,n=state(service,3.9);near(s['pose_mm'],r['points'][-1],.05)
        record.update(status=f'arrived_slot{slot}_held_support_inspection_pending',final=s,final_native=n)
        return dict(ok=True,slot=slot,record=str(path),pose_mm=s['pose_mm'],payload='held',release_sent=False)
    except BaseException as e:
        record.update(status='stopped_or_uncertain',error=str(e))
        if record['motion_sent']:
            try:record['stop']=service.program('stop')
            except Exception as x:record['stop_error']=str(x)
        raise
    finally:record['finished_at']=time.time();save()
