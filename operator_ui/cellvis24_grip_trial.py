"""Explicit supervised Cellvis grip trial, same closure policy as48-well.

No startup, reconnect, retries, lift, force-limit writes or success acceptance.
Requires the genuine Cellvis open-claw trial and operator height/spacing check.
"""
import argparse
import json
import math
from pathlib import Path
import time
from urllib.request import Request,urlopen
from uuid import uuid4
from draggo import DragGoRPC
from gripper_closure import closure_plan

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'
PROFILE=ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis_p24_1_5h_n.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    plan=closure_plan(28,3.9)
    if not args.execute:print(json.dumps(plan,indent=2));return
    profile=json.loads(PROFILE.read_bytes());prior=json.loads((FOLDER/'open_claw_run.json').read_bytes())
    if prior['status']!='open_claw_trial_completed_awaiting_inspection' or not profile['handling']['operator_centering_and_height_acceptance']['accepted']:
        raise RuntimeError('Accepted open-claw setup required')
    expected=prior['phases'][-1]['final']['robot']['pose_mm']
    # A prior dispatched attempt must be reviewed explicitly, never repeated.
    for p in FOLDER.glob('cellvis_grip_*.json'):
        if json.loads(p.read_bytes()).get('steps'):raise RuntimeError('A closure was already attempted; review it before another trial')
    out=FOLDER/('cellvis_grip_'+uuid4().hex+'.json')
    record=dict(status='checking',plan=plan,expected_pose=expected,steps=[],lift_sent=False,force_limits_changed=False)
    def save():out.write_text(json.dumps(record,indent=2))
    def api(path,body=None):
        req=Request('http://127.0.0.1:5002/'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Cephla-View':'developer'})
        with urlopen(req,timeout=30) as f:v=json.load(f)
        if v.get('ok') is False or v.get('recovered') or v.get('gripper_warning'):raise RuntimeError(str(v))
        return v
    def check():
        s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
        if not r.get('connected') or r.get('errors') or not r.get('enabled') or r.get('control_mode',{}).get('mode')!='auto' or r.get('program_state',{}).get('state')!='running' or s['sequence'].get('active'):
            raise RuntimeError('Controller not ready; no reset/retry')
        if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):raise RuntimeError('Native state not ready')
        if any(abs(r['pose_mm'][k]-expected[k])>.05 for k in ('X','Y','Z','Rz')) or not 1.75<=n['external_axes']['E2']<=1.82:raise RuntimeError('Arm or holder moved')
        return s,n
    try:
        s,n=check();record.update(before=s,before_native=n)
        if not 27.98<=n['external_axes']['E1']<=28.05:raise RuntimeError('Jaws not fully open')
        record['baseline']=api('gripper',{'action':'torque'});save()
        previous=n['external_axes']['E1']
        for step in plan['commands']:
            s,n=check()
            if abs(n['external_axes']['E1']-previous)>.05:raise RuntimeError('Jaw changed before closure')
            item=dict(command=step,status='dispatching',at=time.time());record['steps'].append(item);save()
            response=api('gripper',dict(action='move',e1=step['target_e1_mm'],speed=step['speed']))
            item['response']=response;save();deadline=time.monotonic()+2;stable=0
            while stable<3:
                s,n=check();actual=n['external_axes']['E1']
                stable=stable+1 if math.isfinite(actual) and abs(actual-step['target_e1_mm'])<=.07 else 0
                if time.monotonic()>deadline:raise RuntimeError('Grip did not settle; no further closure')
                if stable<3:time.sleep(.1)
            report=api('gripper',{'action':'torque'});item.update(status='completed',actual_e1_mm=actual,torque_report=report);save()
            if not report.get('telemetry_live') or not math.isfinite(report['e1_torque']) or abs(report['e1_position']-step['target_e1_mm'])>.07:raise RuntimeError('Grip feedback unverified')
            check();previous=actual
            print(json.dumps(dict(phase=step['phase'],actual_e1_mm=actual,torque_report=report)),flush=True)
        for _ in range(20):
            time.sleep(.1);s,n=check()
            if abs(n['external_axes']['E1']-3.9)>.07:raise RuntimeError('Jaw position changed after closing')
        record.update(status='closure_completed_grasp_unverified',final=s,final_native=n,completed_at=time.time())
    except Exception as error:
        record.update(status='stopped_or_uncertain',error=str(error));raise
    finally:save();print(str(out),flush=True)


if __name__=='__main__':main()
