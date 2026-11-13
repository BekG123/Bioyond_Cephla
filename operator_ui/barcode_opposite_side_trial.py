"""One source-bound released-holder half-turn and open-jaw pickup inspection.

No grip, scanner transport, startup, retries, or registration. The rotated
plate's centering must be observed before a separately checked pickup.
"""
import json
import math
import secrets
import time
from pathlib import Path
from uuid import uuid4

from autonomy import TransferError
from calibration_e2 import accepted
from cellvis24_workflow import source_record,sha
from cellvis24_scanner_return import RUNS,geometry
from home_hamilton_exchange import native,holder_restore_targets
from holder_contact_monitor import holder_ok
from home_squid_transfer import checked
from scope_step_trial import near,preflight
from trajectory_queue import LuaTrajectory,prepare_points
from run_record_io import write_run_record

TARGET=181.77
OUTPUT=Path(__file__).parent/'reports/plate_session/barcode_opposite_trials'


def snapshot(service,pose,expected_angle):
    s=preflight(service);n=native(service)
    if any(n.get(k,True) for k in ('moving','manual','drag','error','emergency')):
        raise TransferError('Stationary fault-free Auto required.')
    axes=n['external_axes']
    if any(not math.isfinite(axes[k]) for k in ('E1','E2')) or abs(axes['E1']-28)>.07:
        raise TransferError('Released empty jaws28 required; no plate may be held during rotation.')
    if not holder_ok(axes['E2'],expected_angle,contact=True):
        raise TransferError('Holder outside shared Hamilton feedback tolerance.')
    near(s['pose_mm'],pose,.05)
    return s,n


def plan(service,cfg,source,target=None,*,prepare_original=False):
    if type(prepare_original) is not bool:raise TransferError('Invalid holder preparation option.')
    requested_target=target
    if requested_target not in (None,1.77,TARGET):raise TransferError('Unknown inspected scanner orientation.')
    source,d=source_record(source)
    target=TARGET
    if source.name=='release_restore.json':
        # Repeat the accepted original-side pickup from a completed release;
        # no camera calibration or holder half-turn belongs in this phase.
        from barcode_opposite_pickup import source_data
        pickup=json.loads(Path(d['plan']['binding']['source']).read_bytes())
        _,_,g=source_data(pickup['source'],require_fresh=False);target=1.77
    elif source.name=='hotel_home.json':
        from hotel_cellvis_handoff import validate_source
        g=validate_source(source,d);target=1.77
    elif source.name=='recovered_home.json':
        from cellvis_recovery_handoff import validate_source
        g=validate_source(source,d);target=1.77
    elif source.parent.parent==RUNS.resolve() and source.name=='release_home.json':
        g=geometry(source.parent.name)
    else:
        raise TransferError('Completed recent scanner-return release required.')
    if requested_target is not None:target=requested_target
    if cfg!=g['cfg']:raise TransferError('IK configuration changed.')
    s=preflight(service);n=native(service);angle=n['external_axes']['E2']
    if not (holder_ok(angle,1.77,contact=True) if prepare_original else accepted(angle)):
        raise TransferError(f'Original holder angle required: measured {angle:.6f} degrees; '+
            ('outside the bounded correction range.' if prepare_original else 'no correction included in this plan.'))
    snapshot(service,g['station_clearance'],angle)
    if {k:list(v) for k,v in service.envelope.items()}!={'X':[200.,450.],'Y':[-250.,380.],'Z':[70.,400.]}:
        raise TransferError('Original workspace required.')
    near(s['pose_mm'],d['final']['pose_mm'],.05)
    for f in OUTPUT.glob('*/run.json'):
        if json.loads(f.read_bytes()).get('plan',{}).get('source')==str(source):
            raise TransferError('This half-turn was already attempted; inspect before any retry.')
    q=checked(s['pose_mm'],[g['clearance']],s['joints'],cfg,service.envelope)
    checked(g['clearance'],[g['seat']],q,cfg,service.envelope)
    prepare_points(g['clearance'],q,[g['seat']],cfg,reviewed=True,home_transit=True)
    cap=LuaTrajectory(service).capability()
    if not cap.get('available') or cap.get('version')!=220109:raise TransferError('Running published queue required.')
    return dict(id=uuid4().hex,source=str(source),source_sha256=sha(source),geometry=g,
        start=s['pose_mm'],joints=s['joints'],e2=angle,targets=[] if target==1.77 else holder_restore_targets(1.77 if prepare_original else angle,target),
        prepare_original=prepare_original,
        target=target,at=time.time(),grip_authorized=False,
        implementation_sha256=sha(Path(__file__)))


def execute(run,service,cfg,approved):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Preview expired; no motion sent.')
    options={'prepare_original':True} if approved.get('prepare_original') else {}
    fresh=plan(service,cfg,approved['source'],approved['target'],**options)
    if fresh.get('prepare_original',False)!=approved.get('prepare_original',False):
        raise TransferError('Holder preparation changed after preview.')
    for k in ('source_sha256','geometry','target','implementation_sha256'):
        if fresh[k]!=approved[k]:raise TransferError('Opposite-side trial changed: '+k)
    planned_targets=[] if approved['target']==1.77 else holder_restore_targets(1.77 if approved.get('prepare_original') else approved['e2'],TARGET)
    if approved['targets']!=planned_targets:
        raise TransferError('Rotation targets changed after preview.')
    near(fresh['start'],approved['start'],.05)
    if abs(fresh['e2']-approved['e2'])>.05 or any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Trial start changed.')
    folder=OUTPUT/fresh['id'];folder.mkdir(parents=True,exist_ok=False);path=folder/'run.json'
    record=dict(status='checking',plan=approved,steps=[],samples=[],motion_sent=False,payload='empty',grip_authorized=False)
    def save():write_run_record(path,record)
    def require(r):
        if not r.get('ok') or r.get('recovered'):raise TransferError('Command uncertain; no retry: '+str(r))
        return r
    expected=fresh['e2'];pose=fresh['start'];save()
    try:
        if approved.get('prepare_original'):
            # A completed release receipt establishes custody, not indefinitely
            # stable live angle feedback. Center once at this last clearance
            # checkpoint; the fresh plan already bound source, pose and IK.
            from cellvis_recovery_handoff import restore_segments
            near(pose,fresh['geometry']['station_clearance'],.05)
            def check_original(expected_angle):
                if run.stopped():raise TransferError('Stopped before barcode holder preparation.')
                s,n=snapshot(service,pose,expected_angle)
                angle=n['external_axes']['E2']
                if not holder_ok(angle,1.77,contact=True) or abs(angle-expected_angle)>.1:
                    raise TransferError('Holder changed or correction arrival mismatch; no retry.')
                return s,n
            def dispatch_original():record['motion_sent']=True;save()
            def original_segment(item):
                record['steps'].append(dict(kind='prepare_original_before_pickup',**item));save()
            run.say('Barcode pickup: center released HOME holder at 1.77 degrees, then verify.')
            restore_segments(run,service,[1.77],expected,check_original,require,dispatch_original,original_segment)
            expected=1.77
            for _ in range(3):
                s,n=check_original(expected)
                if not accepted(n['external_axes']['E2']):
                    raise TransferError('Original holder correction not verified; no pickup or retry.')
                time.sleep(.1)
        for target in approved['targets']:
            if run.stopped():raise TransferError('Stopped before holder segment.')
            def rotate():
                s,n=snapshot(service,pose,expected);origin=n['external_axes']['E2']
                if abs(target-origin)>90.01 or abs(target)>360:raise TransferError('Published rotation limit exceeded.')
                token=secrets.randbelow(1000000)+1
                require(service._hostpoint({7:float(token)},13,5))
                if service.robot.get_sys_var_i([7,8])!={7:token,8:250104}:raise TransferError('Holder protocol mismatch.')
                snapshot(service,pose,origin)
                if run.stopped():raise TransferError('Stopped before rotation dispatch.')
                record['motion_sent']=True;save()
                return service._hostpoint({7:float(token),8:origin,9:target},14,120)
            run.say(f'Present opposite barcode: released holder to {target:.3f} degrees.')
            result=require(service._locked(rotate));expected=target
            s,n=snapshot(service,pose,expected)
            record['steps'].append(dict(target=target,result=result,actual=n['external_axes']['E2']));save()
        g=fresh['geometry']
        for label,point,flags in [('Connect above prior long-side pickup',g['clearance'],{}),
                                  ('Open-jaw opposite-side alignment inspection',g['seat'],{'home_transit':True})]:
            if run.stopped():raise TransferError('Stopped before open-jaw trial.')
            s,n=snapshot(service,pose,expected)
            def monitor(*args):
                current=preflight(service);axes=native(service)
                if run.stopped() or abs(axes['external_axes']['E1']-28)>.1 or not holder_ok(axes['external_axes']['E2'],expected,contact=True):
                    raise TransferError('Stop, jaw or holder change during empty approach.')
                record['samples'].append(dict(at=time.time(),pose=current['pose_mm'],axes=axes['external_axes']));save()
            run.say(label);record['motion_sent']=True;save()
            result=require(LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],[point],cfg,5,monitor,reviewed=True,**flags))
            pose=point;s,n=snapshot(service,pose,expected)
            record['steps'].append(dict(label=label,target=point,result=result));save()
        record.update(status='awaiting_rotated_plate_centering_observation',final=s,final_native=n)
        return dict(ok=True,status=record['status'],record=str(path),pose_mm=s['pose_mm'],holder_angle=n['external_axes']['E2'],grip_sent=False)
    except BaseException as e:
        record.update(status='stopped_or_uncertain',error=str(e))
        if record['motion_sent']:
            try:record['stop']=service.program('stop')
            except Exception as stop:record['stop_error']=str(stop)
        raise
    finally:
        record['finished_at']=time.time();save()
