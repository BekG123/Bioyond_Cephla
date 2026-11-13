"""Pinned empty-arm trials; current selection crosses Hamilton at Z77.

No enable, reset, restart, jaw commands or automatic retries.
"""
import hashlib
import json
import math
import time
from uuid import uuid4

from autonomy import TransferError, check_path
from hamilton_empty_clearance import FOLDER, IDLE_JOINTS, reference, instrument_ready
from home_hamilton_exchange import native
from scope_step_trial import preflight, near
from run_record_io import write_run_record

PROFILES = ('empty_rack03_idle','empty_rack03_hamilton')
PLAN = FOLDER/'rack_clearance_revision03_headspace_candidate.json'
SHA = '03fd0393e963eb98e0b2fe7a5837277332f8ed0ed793bedc859e9840be3ad659'
PROFILES04 = ('empty_rack04_home','empty_rack04_hamilton')
PLAN04 = FOLDER/'rack_clearance_revision04_home_connector.json'
SHA04 = '060e3d78edb9742d7807d891b6dbc047a69b6f80ffa5f937316089b566f2a476'
ORIGINAL_PROFILES = ('empty_original40_home','empty_original40_hamilton')
ORIGINAL_PLAN = FOLDER/'original_overhead40_roundtrip.json'
ORIGINAL_SHA = 'fdaa6b4691bfbc2aed2f08d1763f5462b5ea174acdde97a1f007698a3bd08ec8'
TURN05_PROFILES = ('empty_turn05_home','empty_turn05_hamilton')
TURN05_PLAN = FOLDER/'corrected_turn05_overhead40.json'
TURN05_SHA = 'afd86476e75c4deeb5d19218287e9b39868357c9a90422471672992455e28d04'
Z77_PROFILES = ('empty_rack06_home','empty_rack06_hamilton')
Z77_PLAN = FOLDER/'corrected_turn06_z77.json'
Z77_SHA = 'f58b885b888fedf1472f696f889ad4f108cd0754d8a5d983602a4147bb5a6649'
FAST_PROFILES = ('empty_rack07_home','empty_rack07_hamilton')
FAST_PLAN = FOLDER/'corrected_turn07_z77_speed137.json'
FAST_SHA = '640e480fc55f3903d76ec7dc18b6a5134bcc880641cfc45daec04b1b0def41df'


def fast_reference():
    raw=FAST_PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=FAST_SHA:raise TransferError('Speed137 rack route changed.')
    p=json.loads(raw);previous,parent=z77_reference()
    for name in ('forward','reverse'):
        if p[name]['points']!=previous[name]['points'] or p[name]['start']!=previous[name]['start']:
            raise TransferError('Speed137 rack route geometry changed.')
    return p,parent


def z77_reference():
    raw=Z77_PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=Z77_SHA:raise TransferError('Z77 route changed.')
    p=json.loads(raw);parent=reference()
    if p['forward']['points'][-1]!=parent['routes']['forward']['points'][-1]:
        raise TransferError('Hamilton destination changed.')
    return p,parent


def turn05_reference():
    raw=TURN05_PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=TURN05_SHA:raise TransferError('Corrected turning waypoint changed.')
    p=json.loads(raw);parent=reference()
    if p['forward']['points'][-1]!=parent['routes']['forward']['points'][-1]:
        raise TransferError('Hamilton destination changed.')
    return p,parent


def original_reference():
    raw=ORIGINAL_PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ORIGINAL_SHA:raise TransferError('Original route candidate changed.')
    p=json.loads(raw);parent=reference()
    if p['routes']['hamilton']['points'][-1]!=parent['routes']['forward']['points'][-1]:
        raise TransferError('Hamilton destination changed.')
    return p,parent


def reference04():
    raw=PLAN04.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA04:raise TransferError('Z67 HOME connector changed.')
    p=json.loads(raw);parent=reference()
    if p['routes']['hamilton']['points'][-1]!=parent['routes']['forward']['points'][-1]:
        raise TransferError('Hamilton destination changed.')
    return p,parent


def reference03():
    raw=PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise TransferError('Rack candidate changed.')
    p=json.loads(raw);parent=reference()
    if p['forward']['points'][-1]!=parent['routes']['forward']['points'][-1]:
        raise TransferError('Hamilton destination changed.')
    return p,parent


def route(profile):
    if profile in FAST_PROFILES:
        p,_=fast_reference();r=p['reverse' if profile==FAST_PROFILES[0] else 'forward']
        return r,r['start_joints']
    if profile in Z77_PROFILES:
        p,_=z77_reference();r=p['reverse' if profile==Z77_PROFILES[0] else 'forward']
        return r,r['start_joints']
    if profile in TURN05_PROFILES:
        p,_=turn05_reference();r=p['reverse' if profile==TURN05_PROFILES[0] else 'forward']
        return r,r['start_joints']
    if profile in ORIGINAL_PROFILES:
        p,_=original_reference();r=p['routes']['home' if profile==ORIGINAL_PROFILES[0] else 'hamilton']
        return r,r['start_joints']
    if profile in PROFILES04:
        p,_=reference04();r=p['routes']['home' if profile==PROFILES04[0] else 'hamilton']
        return r,r['start_joints']
    p,_=reference03()
    if profile not in PROFILES:raise TransferError('Unknown rack route.')
    r=p['return_to_idle' if profile==PROFILES[0] else 'forward']
    source=p['live_state']['joints'] if profile==PROFILES[0] else IDLE_JOINTS
    return r,source


def validate_shape(start,points,profile):
    r,_=route(profile);near(start,r['start'],.05)
    if points!=r['points']:raise TransferError('Rack route must use its exact reviewed points.')


def validate_speeds(start,points,profile,speeds):
    validate_shape(start,points,profile);r,_=route(profile)
    if speeds!=r['segment_speeds'] or any(type(v) not in (int,float) for v in speeds):
        raise TransferError('Rack speeds must match the pinned profile, retaining seating/departure5.')


def validate_route(start,points,joints,cfg,envelope,profile):
    validate_shape(start,points,profile);r,source=route(profile);_,parent=reference03()
    if cfg!=parent['config']:raise TransferError('IK configuration changed.')
    expected={k:(parent['global_envelope'][k]['min'],parent['global_envelope'][k]['max']) for k in ('X','Y','Z')}
    if {k:tuple(v) for k,v in envelope.items()}!=expected:raise TransferError('Workspace changed.')
    if any(not math.isfinite(joints[k]) or abs(joints[k]-source[k])>.5 for k in IDLE_JOINTS):
        raise TransferError('Rack route starting joint winding changed.')
    q=dict(joints);previous=start;offset=q['J1']-start['Z']
    for point in points:
        q=check_path(previous,point,q,cfg,parent['station_envelope']);q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise TransferError('Joint travel exceeded.')
        previous=point
    if any(abs(q[k]-r['validation']['endpoint_joints'][k])>.5 for k in IDLE_JOINTS):
        raise TransferError('Rack terminal joint winding changed.')
    return q


def profiles_for_start(pose):
    """A separately verified return may already have reached HOME clearance."""
    home=route(PROFILES04[1])[0]['start']
    try:near(pose,home,.05)
    except TransferError:return PROFILES04
    return (PROFILES04[1],)


def original_profiles_for_start(pose):
    home=route(ORIGINAL_PROFILES[1])[0]['start']
    try:near(pose,home,.05)
    except TransferError:return ORIGINAL_PROFILES
    return (ORIGINAL_PROFILES[1],)


def turn05_profiles_for_start(pose):
    home=route(TURN05_PROFILES[1])[0]['start']
    try:near(pose,home,.05)
    except TransferError:return TURN05_PROFILES
    return (TURN05_PROFILES[1],)


def z77_profiles_for_start(pose,direction='roundtrip',profiles=Z77_PROFILES):
    if direction=='home':
        near(pose,route(profiles[0])[0]['start'],.05)
        return (profiles[0],)
    if direction!='roundtrip':raise TransferError('Unknown rack trial direction.')
    home=route(profiles[1])[0]['start']
    try:near(pose,home,.05)
    except TransferError:return profiles
    return (profiles[1],)


def plan(service,cfg,direction='roundtrip'):
    from trajectory_queue import LuaTrajectory, travel_program_blocker
    s=preflight(service);n=native(service)
    if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
        raise TransferError('Stationary fault-free Auto required; no controller restart.')
    pose=s['pose_mm'];joints=s['joints'];phases=[]
    for profile in z77_profiles_for_start(pose,direction,FAST_PROFILES):
        r,_=route(profile)
        joints=validate_route(pose,r['points'],joints,cfg,service.envelope,profile)
        phases.append(dict(profile=profile,points=r['points'],segment_speeds=r['segment_speeds']))
        pose=r['points'][-1]
    cap=LuaTrajectory(service).capability();blocker=travel_program_blocker(cap,137)
    if blocker:raise TransferError(blocker)
    if cap['version']!=220109:raise TransferError('Queue220109 required.')
    instrument_ready()
    axes=n['external_axes']
    if any(not math.isfinite(axes[k]) for k in ('E1','E2')):raise TransferError('External feedback invalid.')
    return dict(id=uuid4().hex,reference_sha256=FAST_SHA,start=s['pose_mm'],joints=s['joints'],
        e1=axes['E1'],e2=axes['E2'],cfg=cfg,phases=phases,speed=137,payload='operator-confirmed empty',direction=direction)


def execute(run,service,cfg,approved):
    from trajectory_queue import LuaTrajectory
    fresh=plan(service,cfg,approved.get('direction','roundtrip'))
    for k in ('reference_sha256','cfg','phases','speed','payload','direction'):
        if approved.get(k)!=fresh[k]:raise TransferError('Approved rack plan changed: '+k)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in IDLE_JOINTS):raise TransferError('Start changed.')
    if abs(fresh['e1']-approved['e1'])>.1:raise TransferError('Jaws changed.')
    ident=approved.get('id','')
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise TransferError('Invalid trial identity.')
    file=FOLDER/('rack07_'+ident+'.json')
    record=dict(status='starting',started_at=time.time(),plan=approved,phases=[],samples=[],
        operator_authorization='Z77 crossing and unchanged Z53.72 placement requested. Execution requires the start endpoint confirmations for empty jaws, clear path, open access, released arm and E-stop supervision.',
        automatic_retries=False,jaw_commands=False,holder_commands=False,physical_result='pending observation')
    with file.open('x') as stream:json.dump(record,stream)
    def save():write_run_record(file,record)
    def monitor(stage,done,total):
        s=preflight(service)
        if abs(s['external_axes']['E1']-fresh['e1'])>.15:raise TransferError('Jaw position changed.')
        record['samples'].append(dict(at=time.time(),phase=record['phases'][-1]['profile'],stage=stage,done=done,total=total,robot=s));save()
        run.say(f'Rack trial {record["phases"][-1]["profile"]}: {stage} {done:.1f}/{total}')
    try:
        for phase in fresh['phases']:
            if run.stopped():raise TransferError('Stopped before phase.')
            s=preflight(service);instrument_ready()
            item=dict(phase,status='starting',started_at=time.time());record['phases'].append(item);save()
            result=LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],phase['points'],cfg,fresh['speed'],
                monitor,reviewed=True,hamilton_short_side=phase['profile'],segment_speeds=phase['segment_speeds'])
            item['result']=result;save()
            if not result.get('ok') or result.get('recovered'):raise TransferError('Uncertain motion; no retry.')
            s=preflight(service);near(s['pose_mm'],phase['points'][-1],.2)
            item.update(status='completed',finished_at=time.time(),final=s);save()
        record.update(status='completed',final=s)
        return dict(ok=True,record=str(file),pose_mm=s['pose_mm'],speed=fresh['speed'],final_descent_speed=5)
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error));raise
    finally:
        record['finished_at']=time.time();save()
