"""Authorized empty-arm IDLE <-> vendor scanner trials at speed137.

No arbitrary targets, gripper/holder commands, enabling, or retries. This module
checks kinematics; the operator must supervise and confirm physical route clearance.
"""
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from autonomy import TransferError, check_path
from scope_step_trial import preflight, near
from trajectory_queue import LuaTrajectory, prepare_points, travel_program_blocker

ROOT = Path(__file__).resolve().parents[1]
START = dict(X=289.97, Y=62.63, Z=248.02, Rz=-3.88)
TARGET = dict(X=80.88, Y=-143.51, Z=189.16, Rz=-1.63)
ORIGINAL = dict(X=(200.,450.), Y=(-250.,380.), Z=(70.,400.))
TRIAL = dict(ORIGINAL, X=(80.,450.))
KEYS = ('X','Y','Z','Rz')


def points():
    return [{k:math.floor((START[k]+(TARGET[k]-START[k])*i/7)*100+.5)/100
             for k in KEYS} for i in range(1,8)]


def route(start, continuous=False):
    if continuous and all(abs(start[k]-TARGET[k]) <= .05 for k in KEYS):
        return list(reversed([dict(START)]+points()[:-1]))
    near(start, START, .05)
    return points()


def validate_route(start, path, joints, cfg, envelope, continuous=False):
    if path != route(start, continuous):
        raise TransferError('Scanner route must use the exact seven checked linear points.')
    if {k:tuple(v) for k,v in envelope.items()} != TRIAL:
        raise TransferError('Scanner route requires the explicitly approved trial envelope.')
    previous, q = start, dict(joints)
    offset = q['J1']-start['Z']
    for point in path:
        q = check_path(previous, point, q, cfg, envelope)
        q['J1'] = point['Z']+offset
        if not 0 <= q['J1'] <= 400 or abs(q['J3']) > 180:
            raise TransferError('Scanner route exceeds joint travel.')
        previous = point
    return q


def continuous_endpoint(start, path, joints, cfg, envelope):
    """Coalesce only this pinned almost-collinear route, never a generic shortcut."""
    validate_route(start, path, joints, cfg, envelope, continuous=True)
    end=path[-1]
    for i,p in enumerate(path,1):
        line={k:start[k]+(end[k]-start[k])*i/7 for k in KEYS}
        if math.dist([p[k] for k in KEYS[:3]],[line[k] for k in KEYS[:3]])>.06 or abs(p['Rz']-line['Rz'])>.06:
            raise TransferError('Scanner points are not on the checked continuous line.')
    q=check_path(start,end,joints,cfg,envelope)
    q['J1']=joints['J1']+end['Z']-start['Z']
    if not 0 <= q['J1'] <= 400 or abs(q['J3'])>180:
        raise TransferError('Continuous scanner move exceeds joint travel.')
    return [dict(end)],q


def plan(service, cfg):
    state = preflight(service)
    if {k:tuple(v) for k,v in service.envelope.items()} != ORIGINAL:
        raise TransferError('Original workspace must be unchanged before scanner preview.')
    path = route(state['pose_mm'], continuous=True)
    validate_route(state['pose_mm'], path, state['joints'], cfg, TRIAL, continuous=True)
    continuous_endpoint(state['pose_mm'], path, state['joints'], cfg, TRIAL)
    prepare_points(state['pose_mm'], state['joints'], path, cfg, reviewed=True)
    blocker = travel_program_blocker(LuaTrajectory(service).capability(), 137)
    if blocker:
        raise TransferError(blocker)
    e1 = state['external_axes']['E1']
    if not isinstance(e1,(int,float)) or not math.isfinite(e1):
        raise TransferError('Missing jaw feedback.')
    return dict(id=uuid4().hex, start=state['pose_mm'], joints=state['joints'], e1=e1,
                execution='continuous_collinear', direction='to_scanner' if path[-1]==TARGET else 'to_idle',
                controller_points=[path[-1]], validation_waypoints=7,
                points=path, speed=137, cfg=cfg, original_envelope=ORIGINAL,
                trial_envelope=TRIAL, target_source='controller/main.bin:main/modScan.lua nominal LP1, no plate offset',
                empty_gripper=True, physical_clearance='operator-confirmed; not established by IK')


def execute(run, service, cfg, approved):
    fresh = plan(service, cfg)
    for key in ('points','speed','cfg','original_envelope','trial_envelope','target_source','empty_gripper','physical_clearance','execution','direction','controller_points','validation_waypoints'):
        if json.dumps(approved.get(key),sort_keys=True) != json.dumps(fresh[key],sort_keys=True):
            raise TransferError('Scanner plan changed: '+key)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')) or abs(fresh['e1']-approved['e1'])>.1:
        raise TransferError('Arm or jaw position changed after preview.')
    ident=approved.get('id','')
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):
        raise TransferError('Invalid scanner trial identity.')
    folder=ROOT/'operator_ui/reports/barcode_scanner';folder.mkdir(parents=True,exist_ok=True)
    path=folder/('position_'+ident+'.json')
    record=dict(status='checking',started_at=time.time(),plan=approved,samples=[],automatic_retries=False,
                gripper_commands=False,holder_commands=False,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    baseline=Path(__file__).parent/'reports/barcode_scanner/position_2d54e33b26d140448a95cd5b88a775d7.json'
    if baseline.exists():
        record['baseline']={'path':str(baseline),'sha256':hashlib.sha256(baseline.read_bytes()).hexdigest()}
    record['queue_source_sha256']=hashlib.sha256(Path(__file__).with_name('trajectory_queue.py').read_bytes()).hexdigest()
    record['change']='Seven checked waypoints coalesced to one MoveL in one queue; exact endpoint stop only.'
    record['operator_acceptance']='pending'
    record['authorization']='User requested continuous scanner repeat at speed137, empty arm, present at E-stop.'
    with path.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def save():path.write_text(json.dumps(record,indent=2),encoding='utf-8')
    changed=False
    def monitor(stage,done,total):
        state=preflight(service)
        if abs(state['external_axes']['E1']-fresh['e1'])>.15:
            raise TransferError('Jaw position changed; no further motion.')
        if {k:tuple(v) for k,v in service.envelope.items()} != TRIAL:
            raise TransferError('Scanner workspace changed during motion.')
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=state));save()
        run.say(f'Scanner {stage}: {done}/{total}')
    try:
        if run.stopped():raise TransferError('Stopped before scanner dispatch.')
        changed=True
        record['envelope_change']=service.set_envelope(*(v for k in ('X','Y','Z') for v in TRIAL[k]));save()
        if not record['envelope_change'].get('ok'):raise TransferError('Trial envelope not applied.')
        result=LuaTrajectory(service).execute(run,fresh['start'],fresh['joints'],fresh['points'],cfg,137,
                                             monitor,reviewed=True,scanner_empty='continuous')
        record['result']=result
        if not result.get('ok') or result.get('recovered'):raise TransferError('Scanner move unconfirmed; no retry.')
        final=preflight(service);near(final['pose_mm'],fresh['points'][-1],.2)
        record.update(status='completed',final=final)
        return dict(ok=True,record=str(path),pose_mm=final['pose_mm'],speed=137,payload='empty per operator')
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        raise
    finally:
        if changed:
            try:record['envelope_restoration']=service.set_envelope(*(v for k in ('X','Y','Z') for v in ORIGINAL[k]))
            except Exception as error:record['envelope_restore_error']=str(error)
            if not record.get('envelope_restoration',{}).get('ok'):
                record['status']='workspace_restoration_failed'
        record['finished_at']=time.time();save()
        run.audit('scanner_empty_trial',record=str(path),status=record['status'])
        if record['status']=='workspace_restoration_failed':
            raise TransferError('Scanner trial ended but original workspace restoration failed; inspect receipt.')
