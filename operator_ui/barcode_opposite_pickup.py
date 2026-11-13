"""One inspected opposite-side grip and 5 mm proof lift, through Flask only."""
import argparse
import json
import math
import time
from pathlib import Path

from barcode_opposite_side_trial import OUTPUT,TARGET
from cellvis24_scanner_return import geometry,sha
from run_cellvis24_workflow import api
from draggo import DragGoRPC
from gripper_closure import closure_plan,grip_feedback_matches
from holder_contact_monitor import holder_ok
from scope_step_trial import near
from autonomy import check_path
from run_record_io import write_run_record


def source_data(source,require_fresh=True):
    source=Path(source).resolve();d=json.loads(source.read_bytes())
    if source.parent.parent!=OUTPUT.resolve() or source.name not in ('run.json','reseat_before_load.json'):
        raise RuntimeError('Use the opposite-side open-jaw trial receipt.')
    if source.name=='reseat_before_load.json':
        prior=source.with_name('pickup.json');p=json.loads(prior.read_bytes())
        trial,_,g=source_data(source.with_name('run.json'),require_fresh=False)
        if (d.get('status')!='released_at_rotated_HOME' or d.get('payload')!='empty' or
            d['source']!=str(prior) or d['source_sha256']!=sha(prior) or
            p['status']!='proof_lift_completed_retention_pending' or p['source_sha256']!=sha(trial)):
            raise RuntimeError('Completed proof-lift reseating required.')
        if require_fresh and not 0<=time.time()-d['finished_at']<=1800:raise RuntimeError('Reseating expired.')
        near(d['final']['robot']['pose_mm'],g['seat'],.05)
        if abs(d['final_native']['external_axes']['E1']-28)>.07:raise RuntimeError('Release not confirmed.')
        return source,d,g
    if d.get('status')!='awaiting_rotated_plate_centering_observation' or d.get('payload')!='empty':
        raise RuntimeError('Completed open-jaw trial required.')
    if require_fresh and not 0<=time.time()-d['finished_at']<=1800:raise RuntimeError('Open-jaw trial expired.')
    g=geometry(d['plan']['geometry']['id'])
    if g!=d['plan']['geometry'] or d['plan']['target'] not in (1.77,TARGET):
        raise RuntimeError('Source geometry changed.')
    near(d['final']['pose_mm'],g['seat'],.05)
    return source,d,g


def run(source,alignment_confirmed=False,*,host=None):
    # Internal host supplies the already-owned console service, never another
    # connection or a second runner. CLI inspection semantics remain unchanged.
    if host is None and alignment_confirmed is not True:raise RuntimeError('Actual centering observation required.')
    call=api if host is None else host.call
    source,d,g=source_data(source)
    trial=json.loads(source.with_name('run.json').read_bytes()) if source.name!='run.json' else d
    holder_target=trial['plan']['target']
    out=source.parent/('pickup_after_load.json' if source.name=='reseat_before_load.json' else 'pickup.json')
    if out.exists():raise RuntimeError('Pickup already attempted; inspect outcome, no retry.')
    r=dict(status='checking',source=str(source),source_sha256=sha(source),geometry=g,
           alignment_observation=('Operator confirmed even spacing, correct height, holder clear.' if host is None
                                  else 'Accepted fixed pickup geometry; current visual observation not asserted.'),
           holder_target=holder_target,grip_target=3.9,steps=[],samples=[],motion_sent=False,
           physical_retention='pending',automatic_retries=False)
    def save():write_run_record(out,r)
    def require(value):
        if value.get('ok') is not True or value.get('recovered') or value.get('gripper_warning'):
            raise RuntimeError('Command failed or uncertain; no retry: '+str(value))
        return value
    def check(pose,expected=None):
        if host is not None:host.check_owner()
        s=call('state');robot=s['robot'];n=DragGoRPC('192.168.201.220').info() if host is None else host.native()
        if (not robot.get('connected') or robot.get('errors') or not robot.get('enabled')
            or robot.get('control_mode',{}).get('mode')!='auto'
            or robot.get('program_state',{}).get('state')!='running'
            or not robot.get('lua_app_initialized') or (host is None and s['sequence'].get('active'))
            or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual'))):
            raise RuntimeError('Healthy stationary running Auto required.')
        near(robot['pose_mm'],pose,.05)
        axes=n['external_axes']
        if not all(math.isfinite(axes[k]) for k in ('E1','E2')) or not holder_ok(axes['E2'],holder_target,True):
            raise RuntimeError('Holder outside shared Hamilton tolerance.')
        if expected is not None:
            good=abs(axes['E1']-28)<=.07 if expected==28 else grip_feedback_matches(axes['E1'],expected)
            if not good:raise RuntimeError('Jaw feedback changed.')
        r['samples'].append(dict(at=time.time(),pose=robot['pose_mm'],axes=axes));save()
        return s,n
    with out.open('x') as f:json.dump(r,f)
    try:
        if host is None and not call('state')['robot'].get('connected'):require(call('connect',{'ip':'192.168.201.220'}))
        s,n=check(g['seat'],28)
        if host is None:
            ui=call('researcher/api/lacry/state')
            if ui.get('running',{}).get('active') or ui.get('pending'):raise RuntimeError('Another workflow owns the arm.')
        cfg=call('robot_params')
        env={k:[s['envelope'][k]['min'],s['envelope'][k]['max']] for k in ('X','Y','Z')}
        if cfg!=g['cfg'] or not s['envelope']['enabled'] or env!={'X':[200,450],'Y':[-250,380],'Z':[70,400]}:
            raise RuntimeError('Configuration or original workspace changed.')
        lift=dict(g['seat'],Z=round(g['seat']['Z']+5,3))
        check_path(g['seat'],lift,s['robot']['joints'],cfg,env)
        r.update(cfg=cfg,lift_target=lift,lift_speed=5,closure=closure_plan(28,3.9));save()
        previous=28
        for command in r['closure']['commands']:
            check(g['seat'],previous)
            r['motion_sent']=True;save()
            result=require(call('gripper',dict(action='move',e1=command['target_e1_mm'],speed=command['speed'])))
            stable=0;deadline=time.monotonic()+2
            while stable<3:
                s,n=check(g['seat'])
                stable=stable+1 if grip_feedback_matches(n['external_axes']['E1'],command['target_e1_mm']) else 0
                if time.monotonic()>deadline:raise RuntimeError('Jaw arrival uncertain; no lift.')
                if stable<3:time.sleep(.1)
            torque=require(call('gripper',{'action':'torque'}))
            if not torque.get('telemetry_live') or not math.isfinite(torque['e1_torque']) or not grip_feedback_matches(torque['e1_position'],command['target_e1_mm']):
                raise RuntimeError('Fresh grip feedback unavailable.')
            r['steps'].append(dict(command=command,response=result,torque=torque));save()
            previous=command['target_e1_mm']
        for _ in range(20):check(g['seat'],3.9);time.sleep(.1)
        r['steps'].append(dict(kind='proof_lift',target=lift,speed=5,status='dispatching'));save()
        result=require(call('move',dict(x=lift['X'],y=lift['Y'],z=lift['Z'],rz=lift['Rz'],speed=5,interpolation='linear')))
        s,n=check(lift,3.9)
        r['steps'][-1].update(status='completed',response=result)
        r.update(status='proof_lift_completed_retention_pending',final=s,final_native=n)
    except BaseException as e:
        r.update(status='stopped_or_uncertain',error=str(e))
        if r['motion_sent']:
            try:r['stop']=call('program',{'action':'stop'})
            except Exception as stop:r['stop_error']=str(stop)
        raise
    finally:
        r['finished_at']=time.time();save()
        print(json.dumps(dict(status=r['status'],record=str(out))),flush=True)
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--alignment-confirmed',action='store_true')
    p.add_argument('--execute',action='store_true')
    a=p.parse_args()
    if a.execute:run(a.source,a.alignment_confirmed)
    else:
        _,_,g=source_data(a.source)
        print(json.dumps(dict(motion_started=False,seat=g['seat'],grip=closure_plan(28,3.9),lift_mm=5,lift_speed=5)))
