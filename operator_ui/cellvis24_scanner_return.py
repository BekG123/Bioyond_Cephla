"""Reverse the completed Cellvis scanner route, then release at measured HOME.

Separate return/release receipts preserve the physical support inspection.
No holder rotation, startup, fault recovery, or Hamilton movement here.
"""
import hashlib
import json
import math
import re
import time
from pathlib import Path
from uuid import uuid4

from autonomy import TransferError
from calibration_e2 import accepted
from holder_contact_monitor import holder_ok
from home_hamilton_exchange import native
from home_squid_transfer import checked
from scope_step_trial import near,preflight
from scope_compact137 import HoldingService
from scanner_empty_route import ORIGINAL,TRIAL,TARGET,KEYS
from cellvis24_scanner_route import checked_geometry
from run_record_io import write_run_record

ROOT=Path(__file__).resolve().parents[1]
TRIALS=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'
RUNS=ROOT/'operator_ui/reports/plate_session/cellvis24_scanner_returns'
RECOVERIES=ROOT/'operator_ui/reports/plate_session/cellvis24_recoveries'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def recovery_evidence(path):
    path=Path(path).resolve()
    if path.parent.parent!=RECOVERIES.resolve() or path.name!='run.json':
        raise TransferError('Use the recorded scanner seating recovery.')
    d=json.loads(path.read_bytes());failure=(ROOT/d['prior_failure']).resolve()
    if (d.get('status')!='empty_clearance_plate_absent' or d.get('plate_absent') is not True
        or failure.parent.parent!=RUNS.resolve() or failure.name!='return_home.json'):
        raise TransferError('Verified empty-arm recovery required.')
    f=json.loads(failure.read_bytes())
    if f.get('status')!='stopped_or_uncertain' or not f.get('error','').startswith('Original HOME holder angle changed'):
        raise TransferError('This review only resolves the inspected scanner seating interruption.')
    g=geometry(failure.parent.name)
    if f['plan']['binding']!=g:raise TransferError('Scanner evidence changed.')
    near(d['final']['pose_mm'],g['station_clearance'],.05)
    if abs(d['final_native']['external_axes']['E1']-28)>.07:raise TransferError('Recovery did not verify open jaws.')
    return d,failure,g

def review_recovered_home(service,cfg,path,plate_seated=False):
    """Read-only re-establishment after manual removal/reseating; never moves."""
    if plate_seated is not True:raise TransferError('Operator must confirm reseated plate and hands clear.')
    path=Path(path).resolve();d,failure,g=recovery_evidence(path)
    if not 0<=time.time()-d['finished_at']<=1800:raise TransferError('Recovery evidence is stale.')
    s=preflight(service);n=native(service)
    if (cfg!=g['cfg'] or n['moving'] or abs(n['external_axes']['E1']-28)>.07
        or not accepted(n['external_axes']['E2']) or not service.envelope_enabled
        or {k:tuple(v) for k,v in service.envelope.items()}!=ORIGINAL):
        raise TransferError('Stationary open jaws, original holder angle and unchanged configuration required.')
    near(s['pose_mm'],g['station_clearance'],.05)
    output=path.with_name('reseated_home.json')
    record=dict(status='operator_reseated_HOME',payload='empty',plate_seated=True,
        recovery=str(path),recovery_sha256=sha(path),failure=str(failure),failure_sha256=sha(failure),
        binding=g,final=s,final_native=n,finished_at=time.time(),motion_sent=False,
        observation='Operator confirmed plate flat in HOME, hands clear and E-stop supervised after empty-arm recovery.')
    with output.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    return dict(ok=True,record=str(output),motion_started=False)

def validate_reseated_source(path,d):
    path=Path(path).resolve()
    if path.parent.parent!=RECOVERIES.resolve() or path.name!='reseated_home.json':
        raise TransferError('Unrecognized HOME recovery source.')
    recovery=path.with_name('run.json');_,failure,g=recovery_evidence(recovery)
    if (d.get('status')!='operator_reseated_HOME' or d.get('payload')!='empty' or d.get('plate_seated') is not True
        or d.get('recovery')!=str(recovery) or d.get('recovery_sha256')!=sha(recovery)
        or d.get('failure')!=str(failure) or d.get('failure_sha256')!=sha(failure) or d.get('binding')!=g):
        raise TransferError('HOME reseating evidence changed or incomplete.')
    near(d['final']['pose_mm'],g['station_clearance'],.05)

def geometry(ident):
    if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident):raise TransferError('Invalid scanner trial ID.')
    folder=TRIALS/ident
    trial=folder/'run.json';grip=folder/'supervised_grip/run.json';lift=folder/'supervised_grip/proof_lift/run.json'
    scan=folder/'supervised_grip/proof_lift/scanner_transfer/run.json'
    t=json.loads(trial.read_bytes());g=json.loads(grip.read_bytes());l=json.loads(lift.read_bytes());s=json.loads(scan.read_bytes())
    if (t['status']!='awaiting_open_claw_inspection' or t['resolved_calibration']['solution']['plate_id']!='cellvis_p24_1_5h_n'
        or g['status']!='closure_completed_grasp_unverified' or g['source_sha256']!=sha(trial)
        or l['status']!='lift_completed_retention_unverified' or l['source_sha256']!=sha(grip)
        or s['status']!='completed' or s['plan']['binding']['id']!=ident
        or s['plan']['binding']['sources']!={str(p.relative_to(ROOT)):sha(p) for p in (trial,grip,lift)}):
        raise TransferError('Matching completed Cellvis scanner evidence required.')
    if not s.get('envelope_restoration',{}).get('ok'):raise TransferError('Scanner workspace restoration was not confirmed.')
    seat={k:t['resolved_calibration']['solution']['endpoint'][k] for k in KEYS}
    proof={k:l['final']['robot']['pose_mm'][k] for k in KEYS}
    near(g['final']['robot']['pose_mm'],seat,.05);near(proof,dict(seat,Z=seat['Z']+5),.05)
    near(s['final']['pose_mm'],TARGET,.05)
    if g['plan']['target_e1_mm']!=3.9 or l['speed']!=5 or l['lift_mm']!=5:raise TransferError('Pickup settings changed.')
    outbound=[dict(proof,Z=300.),dict(TARGET,Z=300.),dict(TARGET)]
    if s['plan']['binding']['points']!=outbound:raise TransferError('Unknown outbound scanner path.')
    from cellvis24_squid_route import geometry as home_geometry
    home=home_geometry()
    return dict(id=ident,start=dict(TARGET),points=[dict(TARGET,Z=300.),dict(proof,Z=300.),proof],
        seat=seat,clearance=dict(seat,Z=round(seat['Z']+30,2)),station_clearance=home['clearance'],cfg=l['cfg'],
        sources={str(p.relative_to(ROOT)):sha(p) for p in (trial,grip,lift,scan)})

class ReturnHoldingService(HoldingService):
    def __init__(self,service,binding):
        super().__init__(service,3.9,{k:list(v) for k,v in TRIAL.items()})
        self.return_binding=binding

def prepare_for_service(service,start,joints,points,cfg,envelope):
    if not isinstance(service,ReturnHoldingService):raise TransferError('Monitored Cellvis return service required.')
    refusal=service._preflight()
    if refusal:raise TransferError(refusal)
    g=geometry(service.return_binding['id'])
    if g!=service.return_binding:raise TransferError('Scanner return evidence changed.')
    return checked_geometry(g,start,joints,points,cfg,envelope)

def plan(service,cfg,ident,phase):
    from trajectory_queue import LuaTrajectory,prepare_points,travel_program_blocker
    if phase not in ('return_home','release_home'):raise TransferError('Unknown scanner return phase.')
    g=geometry(ident);s=preflight(service);n=native(service)
    if (n['moving'] or not service.envelope_enabled or {k:tuple(v) for k,v in service.envelope.items()}!=ORIGINAL
        or not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-3.9)>.07
        or not holder_ok(n['external_axes']['E2'],1.77,contact=phase=='release_home')):
        raise TransferError('Stationary secure long-side grip, original holder angle and workspace required.')
    if cfg!=g['cfg']:raise TransferError('Robot settings changed.')
    if (RUNS/ident/(phase+'.json')).exists():raise TransferError('This phase was already attempted; inspect its outcome, no retry.')
    source_sha=None
    if phase=='return_home':
        near(s['pose_mm'],g['start'],.05)
        _,q=checked_geometry(g,s['pose_mm'],s['joints'],g['points'],cfg,TRIAL)
        q=checked(g['points'][-1],[g['seat']],q,cfg,TRIAL)
        prepare_points(g['points'][-1],q,[g['seat']],cfg,reviewed=True,home_transit=True)
    else:
        source=RUNS/ident/'return_home.json';d=json.loads(source.read_bytes());source_sha=sha(source)
        if d['status']!='at_HOME_held' or not 0<=time.time()-d['finished_at']<=1800:raise TransferError('Fresh completed HOME seating required.')
        if d['plan']['binding']!=g:raise TransferError('HOME seating source changed.')
        near(s['pose_mm'],g['seat'],.05)
        q=checked(g['seat'],[g['clearance'],g['station_clearance']],s['joints'],cfg,ORIGINAL)
        prepare_points(g['seat'],s['joints'],[g['clearance']],cfg,reviewed=True,home_transit=True)
        prepare_points(g['clearance'],q,[g['station_clearance']],cfg,reviewed=True)
    blocker=travel_program_blocker(LuaTrajectory(service).capability(),137)
    if blocker:raise TransferError(blocker)
    return dict(id=uuid4().hex,at=time.time(),phase=phase,binding=g,start=s['pose_mm'],joints=s['joints'],
        e2=n['external_axes']['E2'],source_sha256=source_sha,
        implementation={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__),ROOT/'operator_ui/trajectory_queue.py')})

def execute(run,service,cfg,approved):
    from trajectory_queue import LuaTrajectory
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Return preview expired; no motion sent.')
    fresh=plan(service,cfg,approved['binding']['id'],approved['phase'])
    for key in ('phase','binding','source_sha256','implementation'):
        if fresh[key]!=approved.get(key):raise TransferError('Scanner return plan changed: '+key)
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):raise TransferError('Starting joints changed.')
    if abs(fresh['e2']-approved['e2'])>.05:raise TransferError('Holder moved after preview.')
    g=fresh['binding'];phase=fresh['phase'];folder=RUNS/g['id'];folder.mkdir(parents=True,exist_ok=True)
    path=folder/(phase+'.json')
    record=dict(status='checking',at=time.time(),plan=approved,samples=[],steps=[],motion_sent=False,payload='held',
        support_confirmed=phase=='release_home',automatic_retries=False)
    with path.open('x',encoding='utf-8') as f:json.dump(record,f)
    changed=False;expected_e1=3.9;holding=ReturnHoldingService(service,g)
    holder_contact=phase=='release_home'
    def save():write_run_record(path,record)
    def require(r):
        if not r.get('ok') or r.get('recovered') or r.get('gripper_warning'):raise TransferError('Command uncertain; no retry: '+str(r))
        return r
    def check(stationary=False,check_jaws=True):
        s=preflight(service);n=native(service)
        # Preserve the offending reading too, rather than losing it on refusal.
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes'],holder_contact=holder_contact));save()
        if run.stopped() or (stationary and n['moving']):raise TransferError('Stopped or unsettled.')
        if check_jaws and (not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-expected_e1)>.1):raise TransferError('Grip changed.')
        if not holder_ok(n['external_axes']['E2'],1.77,holder_contact):
            raise TransferError(f"Original HOME holder angle changed: E2={n['external_axes']['E2']:.6f}; contact={holder_contact}.")
        return s,n
    def queue(label,points,speed,owner=service,**flags):
        s,_=check(True);run.say(label);record['motion_sent']=True;save()
        result=require(LuaTrajectory(owner).execute(run,s['pose_mm'],s['joints'],points,cfg,speed,
            lambda *args:check(),reviewed=True,**flags))
        current,_=check(True);near(current['pose_mm'],points[-1],.05)
        record['steps'].append(dict(label=label,result=result));save()
    try:
        check(True)
        if phase=='return_home':
            changed=True;require(service.set_envelope(*(v for k in ('X','Y','Z') for v in TRIAL[k])))
            queue('Scanner to HOME: one reverse queue at137',g['points'],137,holding,scanner_loaded='cellvis_return')
            holder_contact=True
            queue('Seat plate in measured HOME at5',[g['seat']],5,holding,home_transit=True)
            s,n=check(True);record.update(status='at_HOME_held',final=s,final_native=n)
        else:
            check(True);near(service.pose_mm(),g['seat'],.05)
            record['motion_sent']=True;save();record['opening']=require(service.move_gripper(28,5));save()
            stable=0;deadline=time.monotonic()+2
            while stable<3:
                s,n=check(True,False);near(s['pose_mm'],g['seat'],.05)
                stable=stable+1 if abs(n['external_axes']['E1']-28)<=.07 else 0
                if time.monotonic()>deadline:raise TransferError('Release not verified; no lift or rotation.')
                time.sleep(.1)
            expected_e1=28
            queue('Released HOME clearance30mm at137',[g['clearance']],137,home_transit=True,home_speed137=True)
            # Only correct residual compliance with empty jaws above HOME.
            stable=0;corrected=False;deadline=time.monotonic()+1.5
            while stable<3:
                s,n=check(True);near(s['pose_mm'],g['clearance'],.05)
                stable=stable+1 if accepted(n['external_axes']['E2']) else 0
                if time.monotonic()>deadline:
                    if corrected:raise TransferError('Released holder did not settle; no new pickup.')
                    record['holder_settling_correction']=require(service.position_calibration_e2());save()
                    corrected=True;stable=0;deadline=time.monotonic()+1.5
                if stable<3:time.sleep(.1)
            holder_contact=False
            queue('Empty connector to accepted HOME clearance',[g['station_clearance']],5)
            s,n=check(True);record.update(status='completed',final=s,final_native=n,payload='empty')
        return dict(ok=True,status=record['status'],record=str(path),pose_mm=s['pose_mm'],payload=record['payload'])
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
        if record['status']=='workspace_restoration_failed':raise TransferError('Workspace restoration failed.')
