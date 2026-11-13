"""One explicitly requested grip after projected trial2094; never lifts/retries."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
from proof_lift_plate import api
from draggo import DragGoRPC
from gripper_closure import closure_plan
from holder_contact_monitor import holder_ok
from calibration_e2 import accepted
from scope_step_trial import near
from run_record_io import write_run_record

SOURCE=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/2094a75669894864bf1efdfcb4f2c807/run.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    raw=SOURCE.read_bytes();prior=json.loads(raw)
    if prior['status']!='awaiting_open_claw_inspection' or prior.get('payload')!='empty':
        raise RuntimeError('Completed open-jaw trial required.')
    if not all(s['status']=='completed' for s in prior['steps']):raise RuntimeError('Prior motion incomplete.')
    expected=prior['final']['pose_mm'];solution=prior['resolved_calibration']['solution']
    near(expected,solution['endpoint'],.05)
    if solution['grip_e1_mm']!=3.9 or expected['Z']<75.67 or expected['Z']>75.77:
        raise RuntimeError('Cellvis accepted grip/height changed.')
    plan=closure_plan(28.,3.9)
    if not args.execute:
        print(json.dumps(dict(motion_started=False,expected_pose=expected,closure=plan,lift=False),indent=2));return
    if not 0<=time.time()-prior['finished_at']<=1800:raise RuntimeError('Trial receipt stale.')
    folder=SOURCE.parent/'supervised_grip';folder.mkdir(exist_ok=False)
    path=folder/'run.json'
    record=dict(status='checking',at=time.time(),source=str(SOURCE),source_sha256=hashlib.sha256(raw).hexdigest(),
                authorization='User: attempt the same grip at the tested48-well fast speed; approach10, final1mm5. No lift.',
                alignment_visual_acceptance='not separately reported',
                plan=plan,expected_pose=expected,steps=[],samples=[],motion_sent=False,lift_sent=False,
                force_limits_changed=False,grasp_verified=False)
    def save():write_run_record(path,record)
    def require(result):
        if result.get('ok') is not True or result.get('recovered') or result.get('gripper_warning'):
            raise RuntimeError('Command failed or uncertain; no retry: '+str(result))
        return result
    def check(contact=False):
        s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
        if (not r.get('connected') or r.get('errors') or not r.get('enabled') or
                r.get('control_mode',{}).get('mode')!='auto' or
                r.get('program_state',{}).get('state')!='running' or not r.get('lua_app_initialized') or
                s['sequence'].get('active')):
            raise RuntimeError('Controller not healthy stationary running Auto.')
        if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
            raise RuntimeError('Native controller state not ready.')
        near(r['pose_mm'],expected,.05)
        e1,e2=(n['external_axes'][k] for k in ('E1','E2'))
        if not all(math.isfinite(x) for x in (e1,e2)):
            raise RuntimeError('Invalid external-axis feedback.')
        if not (holder_ok(e2,1.77,True) if contact else accepted(e2)):
            raise RuntimeError('Holder outside the existing accepted monitor bounds.')
        record['samples'].append(dict(at=time.time(),pose=r['pose_mm'],axes=n['external_axes']))
        save();return s,n
    try:
        s,n=check();record['before']=s;record['before_native']=n
        if abs(n['external_axes']['E1']-28)>.07:raise RuntimeError('Expected open empty jaws28.')
        ui=api('researcher/api/lacry/state')
        if ui.get('running',{}).get('active') or ui.get('pending'):
            raise RuntimeError('Another workflow owns the arm.')
        record['baseline']=require(api('gripper',{'action':'torque'}));save()
        previous=28.
        for command in plan['commands']:
            s,n=check(contact=record['motion_sent'])
            if abs(n['external_axes']['E1']-previous)>.07:raise RuntimeError('Jaw changed before command.')
            item=dict(command=command,status='dispatching',at=time.time())
            record['steps'].append(item);record['motion_sent']=True;save()
            item['response']=require(api('gripper',dict(action='move',e1=command['target_e1_mm'],speed=command['speed'])))
            save();stable=0;deadline=time.monotonic()+2
            while stable<3:
                s,n=check(contact=True);actual=n['external_axes']['E1']
                stable=stable+1 if abs(actual-command['target_e1_mm'])<=.07 else 0
                if time.monotonic()>deadline:raise RuntimeError('Jaw arrival not verified; stop without retry.')
                if stable<3:time.sleep(.1)
            torque=require(api('gripper',{'action':'torque'}))
            if (not torque.get('telemetry_live') or not math.isfinite(torque['e1_torque']) or
                    abs(torque['e1_position']-command['target_e1_mm'])>.07):
                raise RuntimeError('Fresh settled grip feedback unavailable.')
            item.update(status='completed',actual_e1_mm=actual,torque_report=torque);save()
            previous=command['target_e1_mm']
            print(json.dumps(dict(phase=command['phase'],actual_e1_mm=actual,speed=command['speed'],torque_report=torque)),flush=True)
        for _ in range(20):
            time.sleep(.1);s,n=check(contact=True)
            if abs(n['external_axes']['E1']-3.9)>.07:raise RuntimeError('Grip changed after closure.')
        record.update(status='closure_completed_grasp_unverified',final=s,final_native=n)
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error));save()
        if record['motion_sent']:
            try:record['stop_response']=api('program',{'action':'stop'})
            except Exception as stop:record['stop_error']=str(stop)
        raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(status=record['status'],record=str(path),lift_sent=False)),flush=True)


if __name__=='__main__':main()
