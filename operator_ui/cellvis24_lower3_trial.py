"""One explicitly requested Cellvis regrip3 mm lower, then a5 mm proof lift.

Returns the held plate to its original support before opening and lowering
the empty jaws. No startup, fault reset, automatic motion retry or force edits.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.request import Request,urlopen

from autonomy import check_path
from draggo import DragGoRPC
from gripper_closure import closure_plan

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    old=json.loads((FOLDER/'proof_lift.json').read_bytes())
    if old['status']!='lift_completed_retention_unverified':raise RuntimeError('Unexpected preceding lift record')
    start=old['after']['robot']['pose_mm'];seat=old['before']['robot']['pose_mm']
    lower=dict(seat,Z=seat['Z']-3.0);lift=dict(lower,Z=lower['Z']+5.0)
    plan=dict(start=start,reseat=seat,grip_pose=lower,proof_lift=lift,grip=closure_plan(28,3.9))
    print(json.dumps(plan,indent=2),flush=True)
    if not args.execute:return
    out=FOLDER/'lower3_trial.json'
    if out.exists():raise RuntimeError('This adjustment was already attempted; inspect it, no automatic retry')
    record=dict(status='checking',plan=plan,steps=[],operator_feedback='Lift worked; grip may slip. Lower by0.3 cm for better grip.',force_limits_changed=False)
    def save():out.write_text(json.dumps(record,indent=2))
    def api(path,body=None):
        req=Request('http://127.0.0.1:5002/'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Cephla-View':'developer'})
        with urlopen(req,timeout=30) as r:v=json.load(r)
        if v.get('ok') is False or v.get('recovered') or v.get('gripper_warning'):raise RuntimeError(str(v))
        return v
    def check(pose,e1,allow_active=False):
        s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
        if not r.get('connected') or r.get('errors') or not r.get('enabled') or r.get('control_mode',{}).get('mode')!='auto' or r.get('program_state',{}).get('state')!='running' or not s['envelope']['enabled']:
            raise RuntimeError('Controller state changed; no reset or retry')
        if any(n.get(k,True) for k in ('error','emergency','drag','manual')) or not 1.75<=n['external_axes']['E2']<=1.82:raise RuntimeError('Native/holder state changed')
        if not allow_active and (s['sequence'].get('active') or n['moving']):raise RuntimeError('Unexpected active movement')
        if not math.isfinite(n['external_axes']['E1']):raise RuntimeError('Invalid jaw feedback')
        if e1 is not None and abs(n['external_axes']['E1']-e1)>.07:raise RuntimeError('Jaw feedback mismatch')
        if pose is not None and any(abs(r['pose_mm'][k]-pose[k])>.05 for k in ('X','Y','Z','Rz')):raise RuntimeError('Arm pose changed')
        return s,n
    def move(name,origin,goal,e1):
        s,n=check(origin,e1)
        env={k:[s['envelope'][k]['min'],s['envelope'][k]['max']] for k in ('X','Y','Z')}
        check_path(origin,goal,s['robot']['joints'],api('robot_params'),env)
        item=dict(phase=name,status='dispatching',target=goal,speed=5,before=s);record['steps'].append(item);save()
        item['response']=api('move',dict(x=goal['X'],y=goal['Y'],z=goal['Z'],rz=goal['Rz'],speed=5,interpolation='linear'))
        s,n=check(goal,e1);item.update(status='completed',after=s,native_after=n);save();print(name+' completed',flush=True)
    def jaws(name,pose,origin,target,speed):
        s,n=check(pose,origin)
        item=dict(phase=name,status='dispatching',target_e1_mm=target,speed=speed,before=s);record['steps'].append(item);save()
        item['response']=api('gripper',dict(action='move',e1=target,speed=speed));save()
        # Match ReferenceGrip: wait for three settled samples, not the first
        # post-command report. Preserve the same0.07 mm band and2 s deadline.
        deadline=time.monotonic()+2;stable=0
        while stable<3:
            s,n=check(pose,None)
            stable=stable+1 if abs(n['external_axes']['E1']-target)<=.07 else 0
            if time.monotonic()>deadline:raise RuntimeError('Jaw did not settle; no retry')
            if stable<3:time.sleep(.1)
        report=api('gripper',{'action':'torque'})
        if not report.get('telemetry_live') or not math.isfinite(report['e1_torque']) or abs(report['e1_position']-target)>.07:raise RuntimeError('Fresh grip feedback unavailable')
        item.update(status='completed',after=s,native_after=n,torque_report=report);save();print(json.dumps(dict(phase=name,e1=n['external_axes']['E1'],torque=report['e1_torque'])),flush=True)
    try:
        # Read-only reconnect is allowed only before this trial has sent motion.
        s=api('state');n=DragGoRPC('192.168.201.220').info()
        if s['sequence'].get('active') or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):raise RuntimeError('Not stationary and healthy')
        if not s['robot'].get('connected'):record['connection']=api('connect',{});save()
        record['before'],record['native_before']=check(start,3.9);save()
        move('reseat_held_plate',start,seat,3.9)
        jaws('release_supported_plate',seat,3.9,28,5)
        check(seat,28)
        item=dict(phase='lower_open_jaws_3mm',status='dispatching',target=lower);record['steps'].append(item);save()
        body=dict(x=lower['X'],y=lower['Y'],z=lower['Z'],z_calibrated=lower['Z'],rz=lower['Rz'])
        item['start_reply']=api('seq/descend_lua',body);save();deadline=time.monotonic()+90
        while True:
            time.sleep(.3);s,n=check(None,28,allow_active=True);seq=api('seq')
            item.update(latest_state=s,latest_sequence=seq);save()
            if seq.get('name')!='descend_lua':raise RuntimeError('Sequence ownership changed')
            if not seq.get('active'):
                if not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq.get('result')))
                item.update(status='completed',after=check(lower,28)[0]);save();break
            if time.monotonic()>deadline:api('seq/stop',{});raise RuntimeError('Descent timed out; no retry')
        print('Lower open jaws completed',flush=True)
        previous=28
        for command in plan['grip']['commands']:
            jaws('grip_'+command['phase'],lower,previous,command['target_e1_mm'],command['speed'])
            previous=command['target_e1_mm']
        for _ in range(20):time.sleep(.1);check(lower,3.9)
        move('proof_lift_5mm',lower,lift,3.9)
        record.update(status='proof_lift_completed_retention_inspection_pending',after=check(lift,3.9)[0],torque_report=api('gripper',{'action':'torque'}),finished_at=time.time());save()
    except Exception as error:
        record.update(status='stopped_or_uncertain',error=str(error));save()
        try:
            if api('seq').get('active'):record['stop']=api('seq/stop',{})
        except Exception:pass
        raise
    finally:save();print(str(out),flush=True)


if __name__=='__main__':main()
