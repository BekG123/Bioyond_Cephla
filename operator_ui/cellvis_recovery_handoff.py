"""Explicitly requested scanner restart after completed empty HOME recovery.

Preserves recovery and prior calibration evidence. Restores only the released
holder; no arm travel, grip, calibration, startup or automatic retry.
"""
import json
import math
import secrets
import time
from pathlib import Path
from uuid import uuid4

from autonomy import TransferError
from calibration_e2 import accepted
from cellvis24_scanner_return import geometry, sha
from empty_home_recovery import FOLDER as RECOVERIES, HOME
from home_hamilton_exchange import native, holder_restore_targets
from scope_step_trial import near, preflight
from run_record_io import write_run_record

OUTPUT=Path(__file__).parent/'reports/plate_session/cellvis_recovery_handoffs'


def restore_segments(run,service,targets,origin,check,require,on_dispatch,on_segment):
    """Existing released-holder command sequence; caller owns approval and receipt."""
    expected=origin
    for target in targets:
        if run.stopped():raise TransferError('Handoff stopped.')
        def rotate():
            _,n=check(expected);measured=n['external_axes']['E2']
            if not math.isfinite(target) or abs(target)>360 or abs(target-measured)>90.01:
                raise TransferError('Published holder segment limit exceeded.')
            token=secrets.randbelow(1000000)+1
            require(service._hostpoint({7:float(token)},13,5))
            if service.robot.get_sys_var_i([7,8])!={7:token,8:250104}:raise TransferError('Holder protocol mismatch.')
            check(measured)
            if run.stopped():raise TransferError('Stopped before rotation.')
            on_dispatch()
            return service._hostpoint({7:float(token),8:measured,9:target},14,120)
        run.say(f'Restore released holder to {target:.3f} degrees.')
        result=require(service._locked(rotate));expected=target
        s,n=check(expected)
        on_segment(dict(target=target,actual=n['external_axes']['E2'],result=result))


def recovery_data(path):
    path=Path(path).resolve()
    if path.parent!=RECOVERIES.resolve() or path.suffix!='.json':
        raise TransferError('Use a completed empty HOME recovery receipt.')
    d=json.loads(path.read_bytes())
    if d.get('status')!='completed' or d.get('payload_confirmed_empty') is not True or d.get('experiment_retried') is not False:
        raise TransferError('Empty HOME recovery did not complete.')
    near(d['final']['pose_mm'],HOME,.05)
    if abs(d['final']['external_axes']['E1']-28)>.07:
        raise TransferError('Recovery did not finish with open jaws.')
    return path,d


def snapshot(service,cfg,g,expected=None):
    s=preflight(service);n=native(service)
    if any(n.get(k,True) for k in ('moving','manual','drag','error','emergency')):
        raise TransferError('Healthy stationary Auto required.')
    axes=n['external_axes']
    if any(not math.isfinite(axes[k]) for k in ('E1','E2')) or abs(axes['E1']-28)>.07 or abs(axes['E2'])>360:
        raise TransferError('Open empty jaws and valid holder angle required.')
    if expected is not None and abs(axes['E2']-expected)>.1:
        raise TransferError('Holder changed or arrival mismatch; no retry.')
    if cfg!=g['cfg'] or not service.envelope_enabled or {k:list(v) for k,v in service.envelope.items()}!={'X':[200,450],'Y':[-250,380],'Z':[70,400]}:
        raise TransferError('Configuration/workspace changed.')
    near(s['pose_mm'],HOME,.05);near(s['pose_mm'],g['station_clearance'],.05)
    return s,n


def preview(service,cfg,recovery,trial_id):
    path,d=recovery_data(recovery)
    if not 0<=time.time()-d['finished_at']<=1800:raise TransferError('Recovery evidence expired.')
    g=geometry(trial_id);s,n=snapshot(service,cfg,g)
    near(s['pose_mm'],d['final']['pose_mm'],.05)
    if abs(n['external_axes']['E2']-d['plan']['external_axes']['E2'])>.5:
        raise TransferError('Holder changed since recovery; review setup.')
    for p in OUTPUT.glob('*/recovered_home.json'):
        if json.loads(p.read_bytes()).get('recovery')==str(path):
            raise TransferError('Recovery already handed off; inspect the successor, no retry.')
    return dict(recovery=str(path),recovery_sha256=sha(path),binding=g,start=s['pose_mm'],
        e2=n['external_axes']['E2'],targets=holder_restore_targets(n['external_axes']['E2'],1.77),
        at=time.time(),implementation_sha256=sha(Path(__file__)))


def execute(run,service,cfg,approved):
    if not 0<=time.time()-approved['at']<=120:raise TransferError('Handoff preview expired.')
    fresh=preview(service,cfg,approved['recovery'],approved['binding']['id'])
    for k in ('recovery_sha256','binding','targets','implementation_sha256'):
        if approved[k]!=fresh[k]:raise TransferError('Handoff evidence changed: '+k)
    if abs(fresh['e2']-approved['e2'])>.05:raise TransferError('Holder changed before handoff.')
    folder=OUTPUT/uuid4().hex;folder.mkdir(parents=True,exist_ok=False);path=folder/'recovered_home.json'
    r=dict(status='checking',recovery=fresh['recovery'],recovery_sha256=fresh['recovery_sha256'],
        binding=fresh['binding'],payload='empty',plate_seated=True,plan=approved,
        observation='Operator reseated plate in HOME and requested a new scanner/stations cycle.',
        steps=[],motion_sent=False,automatic_retry=False)
    def save():write_run_record(path,r)
    def require(result):
        if result.get('ok') is not True or result.get('recovered'):raise TransferError('Holder command uncertain; no retry: '+str(result))
        return result
    save()
    try:
        def dispatch():r.update(motion_sent=True);save()
        def segment(item):r['steps'].append(item);save()
        restore_segments(run,service,fresh['targets'],fresh['e2'],
            lambda expected:snapshot(service,cfg,fresh['binding'],expected),require,dispatch,segment)
        for _ in range(3):
            if run.stopped():raise TransferError('Handoff stopped.')
            s,n=snapshot(service,cfg,fresh['binding'],1.77)
            if not accepted(n['external_axes']['E2']):raise TransferError('Original holder orientation not verified.')
            time.sleep(.1)
        r.update(status='completed',final=s,final_native=n)
        return dict(ok=True,record=str(path),holder_angle=n['external_axes']['E2'])
    except BaseException as e:
        r.update(status='stopped_or_uncertain',error=str(e))
        if r['motion_sent']:
            try:r['stop']=service.program('stop')
            except Exception as stop:r['stop_error']=str(stop)
        raise
    finally:r['finished_at']=time.time();save()


def validate_source(path,d):
    path=Path(path).resolve()
    if path.parent.parent!=OUTPUT.resolve() or path.name!='recovered_home.json':raise TransferError('Unknown recovery handoff.')
    recovery,_=recovery_data(d['recovery']);g=geometry(d['binding']['id'])
    if d.get('status')!='completed' or d.get('payload')!='empty' or d.get('plate_seated') is not True or d['recovery_sha256']!=sha(recovery) or d['binding']!=g:
        raise TransferError('Incomplete or changed recovery handoff.')
    near(d['final']['pose_mm'],g['station_clearance'],.05)
    axes=d['final_native']['external_axes']
    if abs(axes['E1']-28)>.07 or not accepted(axes['E2']):raise TransferError('Handoff final state invalid.')
    return g
