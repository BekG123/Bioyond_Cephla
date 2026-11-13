"""Receipt-bound Cellvis proof lift -> saved scanner, one queue at137.

No grip, lift, release, startup or fault reset here. The supervised proof lift
must already be complete and retention/loaded clearance explicitly confirmed.
"""
import hashlib
import json
import math
import re
import time
from pathlib import Path
from uuid import uuid4

from autonomy import TransferError, check_path
from scope_step_trial import preflight, near
from scope_compact137 import HoldingService
from scanner_empty_route import TARGET, ORIGINAL, TRIAL, KEYS
from run_record_io import write_run_record

ROOT=Path(__file__).resolve().parents[1]
RUNS=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def geometry(ident):
    if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident):
        raise TransferError('Invalid Cellvis trial ID.')
    folder=RUNS/ident
    trial_path=folder/'run.json';grip_path=folder/'supervised_grip/run.json'
    lift_path=folder/'supervised_grip/proof_lift/run.json'
    trial=json.loads(trial_path.read_bytes());grip=json.loads(grip_path.read_bytes());lift=json.loads(lift_path.read_bytes())
    if (trial['status']!='awaiting_open_claw_inspection' or
            trial['resolved_calibration']['solution']['plate_id']!='cellvis_p24_1_5h_n' or
            grip['status']!='closure_completed_grasp_unverified' or
            grip['source_sha256']!=digest(trial_path) or
            lift['status']!='lift_completed_retention_unverified' or
            lift['source_sha256']!=digest(grip_path) or
            lift['speed']!=5 or lift['lift_mm']!=5 or grip['plan']['target_e1_mm']!=3.9):
        raise TransferError('Completed matching Cellvis grip and5mm proof lift required.')
    if not 0<=time.time()-lift['finished_at']<=1800:
        raise TransferError('Cellvis proof-lift receipt expired; inspect before reuse.')
    start={k:lift['final']['robot']['pose_mm'][k] for k in KEYS}
    seat=trial['resolved_calibration']['solution']['endpoint']
    near(grip['final']['robot']['pose_mm'],seat,.05)
    near(start,dict(seat,Z=seat['Z']+5),.05)
    if abs(lift['final_native']['external_axes']['E1']-3.9)>.07:
        raise TransferError('Proof lift did not preserve grip.')
    points=[dict(start,Z=300.),dict(TARGET,Z=300.),dict(TARGET)]
    return dict(id=ident,start=start,points=points,cfg=lift['cfg'],
                sources={str(p.relative_to(ROOT)):digest(p) for p in (trial_path,grip_path,lift_path)})


class CellvisHoldingService(HoldingService):
    def __init__(self,service,binding):
        super().__init__(service,3.9,{k:list(v) for k,v in TRIAL.items()})
        self.scanner_binding=binding


def prepare_for_service(service,start,joints,points,cfg,envelope):
    if not isinstance(service,CellvisHoldingService):
        raise TransferError('Cellvis scanner requires its monitored receipt-bound holding service.')
    refusal=service._preflight()
    if refusal:raise TransferError(refusal)
    g=geometry(service.scanner_binding['id'])
    if g!=service.scanner_binding:raise TransferError('Cellvis scanner receipt changed.')
    return checked_geometry(g,start,joints,points,cfg,envelope)


def checked_geometry(g,start,joints,points,cfg,envelope):
    if cfg!=g['cfg'] or points!=g['points'] or {k:tuple(v) for k,v in envelope.items()}!=TRIAL:
        raise TransferError('Cellvis scanner must preserve the exact cleared route/configuration.')
    if not all(math.isfinite(p[k]) for p in [start]+points for k in KEYS):raise TransferError('Invalid scanner coordinates.')
    near(start,g['start'],.05)
    q=dict(joints);previous=start;offset=q['J1']-start['Z']
    for point in points:
        q=check_path(previous,point,q,cfg,envelope);q['J1']=point['Z']+offset
        if not math.isfinite(q['J1']) or not 0<=q['J1']<=400 or abs(q['J3'])>180:
            raise TransferError('Cellvis scanner joint travel exceeded.')
        previous=point
    return [dict(p) for p in points],q


def plan(service,cfg,ident):
    from trajectory_queue import LuaTrajectory,travel_program_blocker
    g=geometry(ident);s=preflight(service)
    if (not service.envelope_enabled or {k:tuple(v) for k,v in service.envelope.items()}!=ORIGINAL or
            abs(s['external_axes']['E1']-3.9)>.07):
        raise TransferError('Original workspace and unchanged Cellvis grip required.')
    checked_geometry(g,s['pose_mm'],s['joints'],g['points'],cfg,TRIAL)
    blocker=travel_program_blocker(LuaTrajectory(service).capability(),137)
    if blocker:raise TransferError(blocker)
    return dict(id=uuid4().hex,binding=g,start=s['pose_mm'],joints=s['joints'],speed=137,
                original_envelope={k:list(v) for k,v in ORIGINAL.items()},
                scanner_envelope={k:list(v) for k,v in TRIAL.items()},
                implementation={str(p.relative_to(ROOT)):digest(p) for p in
                    (Path(__file__),ROOT/'operator_ui/trajectory_queue.py',ROOT/'operator_ui/scanner_empty_route.py')})


def execute(run,service,cfg,approved):
    from trajectory_queue import LuaTrajectory
    fresh=plan(service,cfg,approved['binding']['id'])
    for key in ('binding','speed','original_envelope','scanner_envelope','implementation'):
        if fresh[key]!=approved.get(key):raise TransferError('Cellvis scanner plan changed: '+key)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Joint configuration changed before scanner transfer.')
    folder=RUNS/fresh['binding']['id']/'supervised_grip/proof_lift/scanner_transfer'
    folder.mkdir(exist_ok=False);path=folder/'run.json'
    record=dict(status='checking',at=time.time(),plan=approved,samples=[],motion_sent=False,
                operator_lift_retention_confirmed=True,operator_loaded_route_clear=True,
                authorization='User confirmed plate secure, scanner route clear, hands clear and E-stop supervised.',
                release_sent=False,gripper_commands=False,automatic_retries=False)
    changed=False
    def save():write_run_record(path,record)
    holding=CellvisHoldingService(service,fresh['binding'])
    def monitor(stage,done,total):
        s=preflight(holding)
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=s));save()
        run.say(f'Cellvis scanner {stage}: {done:.0f}/{total}')
    try:
        if run.stopped():raise TransferError('Stopped before scanner dispatch.')
        changed=True
        record['envelope_change']=service.set_envelope(*(v for k in ('X','Y','Z') for v in TRIAL[k]));save()
        if not record['envelope_change'].get('ok'):raise TransferError('Scanner corridor not applied.')
        prepare_for_service(holding,fresh['start'],fresh['joints'],fresh['binding']['points'],cfg,service.envelope)
        record['motion_sent']=True;save()
        result=LuaTrajectory(holding).execute(run,fresh['start'],fresh['joints'],fresh['binding']['points'],cfg,137,
                                            monitor,reviewed=True,scanner_loaded='cellvis_direct')
        record['result']=result;save()
        if result.get('ok') is not True or result.get('recovered'):raise TransferError('Scanner arrival uncertain; no retry.')
        final=preflight(holding);near(final['pose_mm'],TARGET,.2)
        record.update(status='completed',final=final,operator_transfer_retention='pending')
        return dict(ok=True,record=str(path),pose_mm=final['pose_mm'],speed=137,payload='Cellvis plate held')
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        if record['motion_sent']:
            try:record['stop_response']=service.program('stop')
            except Exception as stop:record['stop_error']=str(stop)
        raise
    finally:
        if changed:
            try:record['envelope_restoration']=service.set_envelope(*(v for k in ('X','Y','Z') for v in ORIGINAL[k]))
            except Exception as error:record['envelope_restore_error']=str(error)
            if not record.get('envelope_restoration',{}).get('ok'):record['status']='workspace_restoration_failed'
        record['finished_at']=time.time();save()
        run.audit('cellvis_scanner_transfer',record=str(path),status=record['status'])
        if record['status']=='workspace_restoration_failed':raise TransferError('Scanner workspace restoration failed.')
