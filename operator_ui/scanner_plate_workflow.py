"""Fresh 48-well pickup -> proof lift -> direct scanner, without loaded IDLE.

Wraps the accepted pickup, proof lift and IK return. No copied calibration,
raw controller connection, automatic recovery, release or instrument action.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from autonomy import TransferError, ik, wrap
from scope_step_trial import preflight, near
from scope_compact137 import HoldingService
from trajectory_queue import LuaTrajectory
import scanner_empty_route as scanner
import scanner_direct_route as direct_route
from pickup_holder import PickupHolder

FOLDER=Path(__file__).parent/'reports/barcode_scanner'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ScannerProofLift(PickupHolder):
    steps=PickupHolder.steps[:1]
    completion_action=None
    completion_message='Proof lift complete; plate held for direct scanner travel.'


def require_holding(service,direct=False):
    if not isinstance(service,HoldingService) or service.e1 != 3.9:
        raise TransferError('Loaded scanner requires the 3.9 mm monitored holding service.')
    refusal=service._preflight()
    if refusal:raise TransferError(refusal)
    near(service.pose_mm(),direct_route.geometry()['start'] if direct else scanner.START,.05)


def bind_grip(result):
    if result.get('ok') is not True or result.get('target_e1_mm')!=3.9 or result.get('executor')!='staged_reference_position':
        raise TransferError('Fresh successful 48-well grip required before scanner travel.')
    source=Path(result['record']);receipt=json.loads(source.read_bytes())
    if receipt.get('ok') is not True or receipt.get('target_e1_mm')!=3.9 or not 0<=time.time()-receipt['at']<=600:
        raise TransferError('Scanner grip receipt is stale or incomplete.')
    return dict(path=str(source),sha256=digest(source))


def bind_lift(result,grip_binding,cfg):
    if not result or result.get('ok') is not True:raise TransferError('Fresh successful proof lift required.')
    source=Path(result['record']);receipt=json.loads(source.read_bytes());context=receipt.get('context',{})
    if (receipt.get('status')!='completed' or receipt.get('action')!='Lift' or receipt.get('speed')!=5
        or not 0<=time.time()-receipt.get('finished_at',0)<=60 or context.get('cfg')!=cfg
        or context.get('grip_record')!=grip_binding['path'] or context.get('grip_sha256')!=grip_binding['sha256']):
        raise TransferError('Proof lift is stale or not bound to this grip/configuration.')
    near(receipt['final']['pose_mm'],direct_route.geometry()['start'],.05)
    return dict(path=str(source),sha256=digest(source))


def execute_loaded(run,service,cfg,grip_result,folder,profile_sha,direct=False,lift_result=None):
    from projected_pickup import load
    binding=bind_grip(grip_result)
    if load()[1]!=profile_sha:raise TransferError('Pickup reference changed before scanner travel.')
    lift_binding=bind_lift(lift_result,binding,cfg) if direct else None
    g=direct_route.geometry() if direct else None
    state=preflight(service);near(state['pose_mm'],g['start'] if direct else scanner.START,.05)
    if {k:tuple(v) for k,v in service.envelope.items()}!=scanner.ORIGINAL:
        raise TransferError('Unexpected scanner starting workspace.')
    if not math.isfinite(state['external_axes']['E1']) or abs(state['external_axes']['E1']-3.9)>.1:
        raise TransferError('Grip changed before scanner travel.')
    points=g['points'] if direct else scanner.points()
    if direct:direct_route.prepare(state['pose_mm'],state['joints'],points,cfg,scanner.TRIAL)
    else:scanner.continuous_endpoint(state['pose_mm'],points,state['joints'],cfg,scanner.TRIAL)
    path=Path(folder)/'loaded_scanner.json'
    record=dict(status='checking',started_at=time.time(),grip=binding,profile_sha256=profile_sha,
        start=state,validation_points=points,controller_points=points if direct else [scanner.TARGET],speed=137,
        route='HOME_proof_lift_direct_to_scanner' if direct else 'IDLE_to_scanner',proof_lift=lift_binding,idle_travel=False,
        payload='48well_plate',clearance='operator-confirmed for held plate',samples=[],
        automatic_retries=False,gripper_commands=False,operator_acceptance='pending',
        source_sha256=digest(__file__),queue_sha256=digest(Path(__file__).with_name('trajectory_queue.py')))
    with path.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def save():path.write_text(json.dumps(record,indent=2),encoding='utf-8')
    holding=HoldingService(service,3.9,{k:list(v) for k,v in scanner.TRIAL.items()})
    def monitor(stage,done,total):
        s=preflight(holding)
        record['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=s));save()
        run.say(f'Loaded scanner {stage}: {done:.0f}/{total}')
    changed=False
    try:
        if run.stopped():raise TransferError('Stopped before scanner motion.')
        if bind_grip(grip_result)!=binding:raise TransferError('Grip evidence changed.')
        changed=True
        record['envelope_change']=service.set_envelope(*(v for k in ('X','Y','Z') for v in scanner.TRIAL[k]));save()
        if not record['envelope_change'].get('ok'):raise TransferError('Scanner trial workspace not applied.')
        require_holding(holding,direct=direct)
        record['result']=LuaTrajectory(holding).execute(run,state['pose_mm'],state['joints'],points,cfg,137,
            monitor,reviewed=True,scanner_loaded='direct' if direct else True)
        if record['result'].get('ok') is not True or record['result'].get('recovered'):
            raise TransferError('Loaded scanner completion uncertain; no retry.')
        final=preflight(holding);near(final['pose_mm'],scanner.TARGET,.2)
        record.update(status='completed',final=final)
        return dict(ok=True,record=str(path),pose_mm=final['pose_mm'],payload='48well_plate',speed=137)
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error));raise
    finally:
        if changed:
            try:record['envelope_restoration']=service.set_envelope(*(v for k in ('X','Y','Z') for v in scanner.ORIGINAL[k]))
            except Exception as error:record['envelope_restore_error']=str(error)
            if not record.get('envelope_restoration',{}).get('ok'):record['status']='workspace_restoration_failed'
        record['finished_at']=time.time();save()
        run.audit('scanner_plate_trial',record=str(path),status=record['status'])
        if record['status']=='workspace_restoration_failed':raise TransferError('Workspace restoration failed; inspect scanner receipt.')


class ScannerPlateWorkflow:
    def __init__(self,flow,service,runner,params):
        self.flow,self.service,self.runner,self.params=flow,service,runner,params
        self.folder=None

    def preview(self):
        from plate48_workflow import reference
        from gripper_closure import POLICY
        _,profile_sha,_=reference()
        if [a for a,_,_ in self.flow.steps]!=['Calibrate','Align','Descend','Grip','Lift']:
            raise TransferError('Direct scanner workflow must finish pickup at the proof lift, without IDLE travel.')
        self.flow.transport.configuration_ready()
        s=scanner.plan(self.service,self.params())
        if s['direction']!='to_scanner':raise TransferError('Return empty arm to IDLE before pickup.')
        g=direct_route.geometry();proof=g['start'];q=dict(s['joints'])
        q2,q3=ik(proof['X'],proof['Y'],(q['J2'],q['J3']),s['cfg'])
        q.update(J1=q['J1']+proof['Z']-s['start']['Z'],J2=q2,J3=q3,
                 J4=q['J4']+wrap(proof['Rz']-s['start']['Rz'])-(q2+q3-q['J2']-q['J3']))
        direct_route.prepare(proof,q,g['points'],s['cfg'],scanner.TRIAL)
        return dict(id=uuid4().hex,cfg=s['cfg'],start=s['start'],joints=s['joints'],e1=s['e1'],
            profile_sha256=profile_sha,closure_policy=POLICY,speed=137,proof_lift_speed=5,
            scanner_points=g['points'],controller_points=g['points'],proof_lift_pose=proof,idle_travel_after_pickup=False,
            stages=['Calibrate','Align','Descend','Grip','Lift 5 mm','Direct scanner move via Z300 clearance'],
            payload='same 48-well plate in unchanged HOME holder',release_at_scanner=False,
            original_envelope=s['original_envelope'],trial_envelope=s['trial_envelope'],
            source_sha256=digest(__file__),queue_sha256=digest(Path(__file__).with_name('trajectory_queue.py')),
            direct_route_sha256=digest(Path(direct_route.__file__)))

    def start(self,approved):
        fresh=self.preview()
        for key in fresh:
            if key not in ('id','start','joints','e1') and json.dumps(approved.get(key),sort_keys=True)!=json.dumps(fresh[key],sort_keys=True):
                raise TransferError('Pickup/scanner plan changed: '+key)
        near(fresh['start'],approved['start'],.05)
        if abs(fresh['e1']-approved['e1'])>.05 or any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
            raise TransferError('Arm changed after pickup/scanner preview.')
        ident=approved.get('id','')
        if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise TransferError('Invalid trial identity.')
        folder=FOLDER/('plate_'+ident);folder.mkdir(parents=True,exist_ok=False);self.folder=folder
        record=dict(status='authorized',plan=approved,started_at=time.time(),operator_acceptance='pending',
            authorization='User requested pickup then direct scanner travel without IDLE; confirmed unchanged HOME setup and loaded Z300 crossing/turn/descent clearance; E-stop supervised.')
        def save(): (folder/'run.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        save()
        def finish(result):
            record.update(status='completed' if result.get('ok') else 'stopped_or_uncertain',workflow=result,finished_at=time.time());save()
        def scan():
            results=deepcopy(self.flow.state['results'])
            grips=[v['result'] for v in results if v['sequence']=='position_grip']
            if len(grips)!=1 or self.runner.name!='pickup_slow_lift' or self.runner.result.get('ok') is not True:
                raise TransferError('Fresh pickup and proof lift required; no IDLE step.')
            if self.params()!=fresh['cfg']:raise TransferError('Motion configuration changed during pickup.')
            lift_result=deepcopy(self.runner.result)
            return self.runner.start('scanner_plate_trial',execute_loaded,self.service,self.params(),grips[0],folder,fresh['profile_sha256'],True,lift_result)
        try:
            return self.flow.start(on_finish=finish,continuation=dict(label='Direct loaded scanner move',start=scan,
                message='Plate at nominal scanner pose; grip retained. Operator inspection pending.'))
        except BaseException as error:
            record.update(status='start_refused',error=str(error),finished_at=time.time());save();raise

    def public(self):return dict(workflow=self.flow.public(),folder=str(self.folder) if self.folder else None)
