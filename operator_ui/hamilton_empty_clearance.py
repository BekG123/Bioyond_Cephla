"""Empty IDLE -> above HOME -> taught Hamilton corridor at 40, final descent 5.

Exact commissioning route only; no jaw/holder commands or controller recovery.
IK checks reachability, not rack clearance. Physical clearance is operator checked.
"""
import json
import math
import time
from pathlib import Path
from uuid import uuid4

from autonomy import TransferError, check_path
from cellvis24_hamilton_route import reference, instrument_ready, PLAN_SHA
from home_hamilton_exchange import native
from run_record_io import write_run_record
from scope_step_trial import preflight, near

PROFILE = 'empty_home_hamilton40'
IDLE = dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
IDLE_JOINTS = dict(J1=209.421395,J2=84.876866,J3=52.055949,J4=-140.812829)
SPEEDS = [40,40,40,40,40,5]
FOLDER = Path(__file__).parent/'reports/hamilton_empty_clearance'


def points():
    route=reference()['routes']['forward']
    return [dict(route['start'],Z=106.37)]+route['points']


def validate_shape(start,path,profile):
    if profile!=PROFILE:raise TransferError('Unknown empty Hamilton profile.')
    near(start,IDLE,.05)
    if path!=points():raise TransferError('Empty clearance route differs from its pinned points.')


def validate_speeds(start,path,profile,speeds):
    validate_shape(start,path,profile)
    if speeds!=SPEEDS or any(type(v) not in (int,float) for v in speeds):
        raise TransferError('Empty clearance requires transit40 and final descent5.')


def validate_route(start,path,joints,cfg,envelope,profile):
    validate_shape(start,path,profile)
    p=reference()
    if cfg!=p['config']:raise TransferError('IK configuration changed.')
    expected={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
    if {k:tuple(v) for k,v in envelope.items()}!=expected:raise TransferError('Workspace changed.')
    if any(not math.isfinite(joints[k]) or abs(joints[k]-v)>.5 for k,v in IDLE_JOINTS.items()):
        raise TransferError('IDLE joint winding changed.')
    q=dict(joints);previous=start;offset=q['J1']-start['Z']
    for point in path:
        q=check_path(previous,point,q,cfg,p['station_envelope'])
        q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Joint travel exceeded.')
        previous=point
    endpoint=p['routes']['forward']['validation']['endpoint_joints']
    if any(abs(q[k]-endpoint[k])>.5 for k in IDLE_JOINTS):raise TransferError('Terminal winding changed.')
    return q


def plan(service,cfg):
    from trajectory_queue import LuaTrajectory, travel_program_blocker
    s=preflight(service);n=native(service)
    if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
        raise TransferError('Stationary fault-free running Auto required.')
    path=points();q=validate_route(s['pose_mm'],path,s['joints'],cfg,service.envelope,PROFILE)
    capability=LuaTrajectory(service).capability()
    blocker=travel_program_blocker(capability,40)
    if blocker:raise TransferError(blocker)
    if capability['version']!=220109:raise TransferError('Mixed-speed queue220109 required.')
    instrument_ready()
    axes=n['external_axes']
    if any(not math.isfinite(axes[k]) for k in ('E1','E2')):raise TransferError('Missing external-axis feedback.')
    return dict(id=uuid4().hex,start=s['pose_mm'],joints=s['joints'],points=path,
        speed=40,segment_speeds=SPEEDS,cfg=cfg,reference_sha256=PLAN_SHA,
        e1=axes['E1'],e2=axes['E2'],endpoint_joints=q,payload='operator-confirmed empty')


def execute(run,service,cfg,approved):
    from trajectory_queue import LuaTrajectory
    fresh=plan(service,cfg)
    for key in ('points','speed','segment_speeds','cfg','reference_sha256','payload'):
        if approved.get(key)!=fresh[key]:raise TransferError('Clearance plan changed: '+key)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in IDLE_JOINTS):raise TransferError('Arm changed after preview.')
    if any(abs(fresh[k]-approved[k])>.1 for k in ('e1','e2')):raise TransferError('External axes changed after preview.')
    ident=approved.get('id','')
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise TransferError('Invalid plan identity.')
    FOLDER.mkdir(parents=True,exist_ok=True);file=FOLDER/(ident+'.json')
    record=dict(status='starting',started_at=time.time(),plan=approved,samples=[],
        jaw_commands=False,holder_commands=False,automatic_retries=False,
        operator_clearance_confirmed=True,physical_result='awaiting observation')
    with file.open('x') as stream:json.dump(record,stream)
    def save():write_run_record(file,record)
    def monitor(stage,done,total):
        s=preflight(service)
        if abs(s['external_axes']['E1']-fresh['e1'])>.15:raise TransferError('Jaw position changed.')
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=s));save()
        run.say(f'Empty Hamilton clearance {stage}: {done:.1f}/{total}')
    try:
        if run.stopped():raise TransferError('Stopped before dispatch.')
        result=LuaTrajectory(service).execute(run,fresh['start'],fresh['joints'],fresh['points'],cfg,
            40,monitor,reviewed=True,hamilton_short_side=PROFILE,segment_speeds=SPEEDS)
        record['result']=result
        if not result.get('ok') or result.get('recovered'):raise TransferError('Uncertain motion; no retry.')
        s=preflight(service);near(s['pose_mm'],fresh['points'][-1],.2)
        record.update(status='completed',final=s)
        return dict(ok=True,record=str(file),pose_mm=s['pose_mm'],speed=40,final_descent_speed=5)
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error));raise
    finally:
        record['finished_at']=time.time();save()
