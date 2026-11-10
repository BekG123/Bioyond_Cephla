"""One small restore to the accepted holder angle at Home; slow existing Lua."""
import json
import secrets
import time
from pathlib import Path
from short_side_alignment_trial import reference,FOLDER
from holder_rotation_trial import snapshot

PATH=FOLDER/'restore_taught_angle_repeat02.json'

def review(service,profile='original'):
    if profile in ('full_sequence02','full_sequence03_retry03','full_sequence04'):
        from short_side_direct_transfer import reference as direct_reference
        _,_,grip=direct_reference();target=grip['holder_e2_degrees']
        path=FOLDER/(profile+'_holder_restore.json')
    elif profile=='original':
        prior=json.loads((FOLDER/'restore_taught_angle_repeat01.json').read_bytes())
        if prior.get('motion_sent') is not False or prior.get('error')!='Stopped before holder restore':
            raise ValueError('Previous restore must be verified as no motion sent')
        _,taught=reference();target=taught['e2_degrees'];path=PATH
    else:raise ValueError('Unknown holder restore profile')
    # snapshot checks Home, healthy Auto, stationary and empty closed jaws.
    from draggo import DragGoRPC
    current=DragGoRPC(service._endpoint_addr()[0]).info()['external_axes']['E2']
    if abs(current-target)>.5:raise ValueError('Holder correction exceeds the reviewed half degree')
    if path.exists():raise ValueError('Holder restore already attempted; review its receipt')
    before=snapshot(service,current)
    return dict(before=before,start=current,target=target,profile=profile,path=str(path))

def execute(run,service,approved):
    fresh=review(service,approved.get('profile','original'));path=Path(fresh['path'])
    if abs(fresh['start']-approved['start'])>.05:raise ValueError('Holder changed after review')
    record=dict(status='prepared',at=time.time(),approved=fresh,speed=1,motion_sent=False,
        authorization='Operator confirmed restore taught holder angle at Home and repeat accepted approach.')
    with path.open('x') as f:json.dump(record,f,indent=2)
    def save():path.write_text(json.dumps(record,indent=2))
    def command():
        snapshot(service,fresh['start'])
        if run.stopped():raise ValueError('Stopped before holder restore')
        token=secrets.randbelow(1000000)+1
        result=service._hostpoint({7:float(token)},9,5)
        record['probe']=result
        if not result.get('ok') or result.get('recovered'):raise ValueError('Holder interface unavailable')
        regs=service.robot.get_sys_var_i([7,8]);record['registers']=regs
        if regs!={7:token,8:250102}:raise ValueError('Holder interface version mismatch')
        if run.stopped():raise ValueError('Stopped before holder restore')
        if abs(fresh['target']-fresh['start'])<=.03:
            record['already_at_target']=True
        else:
            record['motion_sent']=True;save()
            result=service._hostpoint({7:float(token),8:fresh['start'],9:fresh['target']},10,30)
            record['response']=result;save()
            if not result.get('ok') or result.get('recovered'):raise ValueError('Holder arrival uncertain; no retry')
        after=snapshot(service,fresh['target']);record['after']=after
        for k in ('J1','J2','J3','J4'):
            if abs(after['robot']['joints'][k]-fresh['before']['robot']['joints'][k])>.1:raise ValueError('Arm joints changed during holder restore')
        if abs(after['native']['external_axes']['E1']-fresh['before']['native']['external_axes']['E1'])>.05:raise ValueError('Jaw moved during holder restore')
        if run.stopped():raise ValueError('Operator stopped holder restore')
        return dict(ok=True,e2=after['native']['external_axes']['E2'],report=str(path))
    try:
        result=service._locked(command)
        if not result.get('ok'):raise ValueError(str(result))
        record.update(status='completed',result=result);return result
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error))
        if record['motion_sent']:
            try:record['stop_response']=service.program('stop')
            except Exception as e:record['stop_error']=str(e)
        raise
    finally:record['finished_at']=time.time();save()
