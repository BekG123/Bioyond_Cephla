"""Camera-relative Cellvis commissioning trial; never closes jaws or changes profiles.

The ordinary full-calibration fixed-reference gate remains unchanged. Prepare
captures fresh images without motion. Trial rechecks them before an open-jaw
alignment/descent and ends awaiting physical inspection, not grip acceptance.
"""
import hashlib
import json
import math
import re
import statistics
import time
from uuid import uuid4

from autonomy import TransferError, alignment_plan, wrap
from calibration_e2 import accepted
from cellvis24_calibration import ROOT, REFERENCE, OBSERVATION, reference, evaluate, capture
from cellvis24_squid_route import geometry
from cellvis24_workflow import evidence
from home_hamilton_exchange import native
from home_squid_transfer import checked
from run_record_io import write_run_record
from scope_step_trial import preflight, near
from trajectory_queue import LuaTrajectory, prepare_points

RUNS=ROOT/'operator_ui/reports/plate_session/cellvis24_adjustments'


def require_trial_enabled():
    raise TransferError('Experimental Cellvis adjustment retired after operator inspection. Use accepted full calibration.')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def implementation_binding():
    paths=['operator_ui/cellvis24_adjustment.py','operator_ui/cellvis24_calibration.py',
           'operator_ui/cellvis24_observation.py','operator_ui/cellvis24_image_pipeline.py',
           'Pick and Hold/Align/plate_pose/grid_preview.py']
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}


def endpoint_from_measurements(measurements):
    """Rigid transform of the original accepted offset, never of a prior trial."""
    assessment=evaluate(measurements)
    if not assessment['ok'] and assessment.get('code')!='reference_mismatch':
        raise TransferError(assessment['message'])
    # A stable reference mismatch may be proposed; poor centering/grid cannot.
    if assessment['max_calibration_error_mm']>.75:
        raise TransferError('Camera centering error exceeds adjustment trial limit.')
    for m in measurements:
        if not all(math.isfinite(v) for corner in m['corners_preview_px'] for v in corner):
            raise TransferError('Invalid measured rim.')
    baseline=reference()['raw_target'];seat=geometry()['seat']
    yaw=statistics.median(wrap(m['target']['rz']-baseline['rz']) for m in measurements)
    target={k:statistics.median(m['target'][k] for m in measurements) for k in ('x','y')}
    target['rz']=baseline['rz']+yaw
    angle=math.radians(yaw);dx=seat['X']-baseline['x'];dy=seat['Y']-baseline['y']
    goal=dict(seat,X=target['x']+math.cos(angle)*dx-math.sin(angle)*dy,
              Y=target['y']+math.sin(angle)*dx+math.cos(angle)*dy,Rz=seat['Rz']+yaw)
    distance=math.hypot(goal['X']-seat['X'],goal['Y']-seat['Y'])
    # Trial scope only, not new automatic calibration acceptance tolerances.
    if distance>1 or abs(yaw)>.5:
        raise TransferError('Adjustment exceeds the 1 mm / 0.5 degree open-jaw trial scope.')
    return dict(endpoint=goal,original_endpoint=seat,measured_target=target,
                endpoint_shift_mm=distance,yaw_delta_deg=yaw,assessment=assessment,
                grip_authorized=False,profile_changed=False,depth_estimated=False)


def checked_route(state,cfg,envelope,adjustment):
    near(state['pose_mm'],OBSERVATION,.05)
    seat=adjustment['endpoint']
    target=dict(x=seat['X'],y=seat['Y'],rz=seat['Rz'],z_calibrated=seat['Z'])
    align=alignment_plan(state['pose_mm'],target,state['joints'],cfg,envelope,300)
    q=checked(state['pose_mm'],align,state['joints'],cfg,envelope)
    descent=[dict(seat,Z=200),dict(seat,Z=seat['Z']+20),seat]
    prepare_points(align[-1],q,descent,cfg,reviewed=True,vertical_runs=True)
    checked(align[-1],descent,q,cfg,envelope)
    return dict(target=target,alignment=align,descent=descent,hover_z=300,
                alignment_speed=5,descent_speed=5)


def stationary(service,run,*,running=False,allow_motion=False):
    s=preflight(service) if running else service.status()
    n=native(service)
    if run.stopped() or not s.get('ok') or not s.get('connected') or s.get('errors'):
        raise TransferError('Connected fault-free stationary arm required.')
    if any(n.get(k,True) for k in ('error','emergency','drag')) or (not allow_motion and n.get('moving',True)):
        raise TransferError('Unexpected movement, controller fault, or hand-guiding state.')
    axes=n['external_axes']
    if not all(math.isfinite(axes[k]) for k in ('E1','E2')) or abs(axes['E1']-28)>.07 or not accepted(axes['E2']):
        raise TransferError('Open empty jaws28 and original holder orientation required.')
    return s,n


def prepare(run,service,cfg,cam):
    require_trial_enabled()
    ident=uuid4().hex;folder=RUNS/ident;folder.mkdir(parents=True,exist_ok=False)
    record=dict(status='measuring',at=time.time(),motion_sent=False)
    def save():write_run_record(folder/'prepare.json',record)
    def check(*args):
        s,n=stationary(service,run);near(s['pose_mm'],OBSERVATION,.05);return s,n
    try:
        before,n=check();g=geometry()
        if cfg!=g['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=g['envelope']:
            raise TransferError('Cellvis configuration changed.')
        record.update(start=before['pose_mm'],joints=before['joints'],e2=n['external_axes']['E2']);save()
        def measured(value):record['measurement']=value;save()
        result=capture(cam,check,folder,measured,require_fixed_reference=False)
        adjustment=endpoint_from_measurements([b['measurement'] for b in result['bursts']])
        route=checked_route(before,cfg,service.envelope,adjustment)
        proposal=dict(id=ident,created_at=time.time(),adjustment=adjustment,route=route,
            cfg=cfg,envelope={k:list(v) for k,v in service.envelope.items()},
            start=before['pose_mm'],joints=before['joints'],e2=record['e2'],
            reference_sha256=hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
            acceptance_sha256=evidence(),geometry_sha256=digest(g),measurement_sha256=digest(result),
            implementation_sha256=implementation_binding(),
            status='awaiting_open_claw_trial',grip_authorized=False)
        write_run_record(folder/'proposal.json',proposal)
        record.update(status='prepared',proposal=proposal)
        return dict(ok=True,proposal=proposal,record=str(folder/'prepare.json'))
    except Exception as error:
        record.update(status='rejected',error=str(error));raise
    finally:record['finished_at']=time.time();save()


def load_proposal(ident):
    if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident):raise TransferError('Invalid adjustment ID.')
    folder=RUNS/ident;p=json.loads((folder/'proposal.json').read_bytes())
    if not 0<=time.time()-p['created_at']<=1800:raise TransferError('Measure a fresh Cellvis adjustment.')
    if p['reference_sha256']!=hashlib.sha256(REFERENCE.read_bytes()).hexdigest() or p['acceptance_sha256']!=evidence() or p['geometry_sha256']!=digest(geometry()):
        raise TransferError('Accepted Cellvis reference changed.')
    if p.get('implementation_sha256')!=implementation_binding():raise TransferError('Measure again with the current image/adjustment implementation.')
    source=json.loads((folder/'prepare.json').read_bytes())
    if source.get('status')!='prepared' or source.get('proposal')!=p or digest(source['measurement'])!=p['measurement_sha256']:
        raise TransferError('Adjustment evidence changed.')
    computed=endpoint_from_measurements([b['measurement'] for b in source['measurement']['bursts']])
    if computed!=p['adjustment']:raise TransferError('Adjustment no longer matches measurements.')
    return folder,p


def execute(run,service,cfg,ident,cam):
    require_trial_enabled()
    folder,p=load_proposal(ident)
    # Atomic one-use claim. Never automatically retry uncertain motion.
    attempt=folder/'trial';attempt.mkdir(exist_ok=False)
    record=dict(status='checking',at=time.time(),proposal=p,motion_sent=False,steps=[])
    def save():write_run_record(attempt/'run.json',record)
    def check(*args,allow_motion=False):return stationary(service,run,running=True,allow_motion=allow_motion)
    def require_ok(result):
        if not result.get('ok') or result.get('recovered'):raise TransferError('Uncertain command result; no retry.')
    try:
        before,n=check();near(before['pose_mm'],p['start'],.05)
        if cfg!=p['cfg'] or {k:list(v) for k,v in service.envelope.items()}!=p['envelope']:
            raise TransferError('Adjustment configuration changed.')
        if abs(n['external_axes']['E2']-p['e2'])>.03 or any(abs(before['joints'][k]-p['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
            raise TransferError('Starting configuration changed.')
        def measured(value):record['fresh_measurement']=value;save()
        result=capture(cam,check,attempt,measured,require_fixed_reference=False)
        fresh=endpoint_from_measurements([b['measurement'] for b in result['bursts']])
        a,b=fresh['endpoint'],p['adjustment']['endpoint']
        if math.hypot(a['X']-b['X'],a['Y']-b['Y'])>.15 or abs(wrap(a['Rz']-b['Rz']))>.1:
            raise TransferError('Plate measurement changed since proposal; no motion.')
        # Keep the reviewed waypoints fixed despite sub-resolution TCP jitter;
        # separately validate the real measured connector to those waypoints.
        route=checked_route(dict(before,pose_mm=p['start']),cfg,service.envelope,p['adjustment'])
        if route!=p['route']:raise TransferError('IK route changed.')
        checked(before['pose_mm'],route['alignment']+route['descent'],before['joints'],cfg,service.envelope)
        cap=LuaTrajectory(service).capability()
        if not cap.get('available') or cap.get('version')!=220109:raise TransferError('Running mixed-speed Lua220109 required.')
        from sequences import seq_align
        check();record['motion_sent']=True;save()
        run.say('Cellvis adjusted alignment; jaws remain open.')
        r=seq_align(run,service,route['target'],300,translation_speed=5);require_ok(r)
        record['steps'].append(dict(kind='alignment',response=r));save()
        current,_=check();near(current['pose_mm'],route['alignment'][-1],.05)
        run.say('Cellvis adjusted descent at speed 5; stop before grip.')
        r=LuaTrajectory(service).execute(run,current['pose_mm'],current['joints'],route['descent'],cfg,5,
            lambda *args:check(allow_motion=True),reviewed=True,vertical_runs=True)
        require_ok(r);record['steps'].append(dict(kind='descent',response=r))
        final,n=check();near(final['pose_mm'],p['adjustment']['endpoint'],.05)
        record.update(status='awaiting_centering_inspection',final=final,final_native=n,
                      grip_authorized=False,calibration_complete=False)
        return dict(ok=True,record=str(attempt/'run.json'),status=record['status'],pose_mm=final['pose_mm'])
    except Exception as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        if record['motion_sent']:
            try:record['stop_response']=service.program('stop')
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:record['finished_at']=time.time();save()
