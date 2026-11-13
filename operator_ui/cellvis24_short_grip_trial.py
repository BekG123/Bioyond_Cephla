"""One Cellvis short-side closure and 5 mm proof lift via the sole Flask owner.

Requires the completed open-jaw trial and separately recorded operator fit
acceptance. Never restarts, resets, changes force limits or retries motion.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.request import Request, urlopen

from autonomy import check_path
from draggo import DragGoRPC
from gripper_closure import closure_plan
from run_record_io import write_run_record
from scope_step_trial import near

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'


def api(path, body=None):
    req=Request('http://127.0.0.1:5002/'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json','X-Cephla-View':'developer'})
    with urlopen(req,timeout=30) as response:value=json.load(response)
    if value.get('ok') is False or value.get('recovered') or value.get('gripper_warning'):
        raise RuntimeError(str(value))
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    source=json.loads((FOLDER/'short_side_open_trial.json').read_bytes())
    acceptance=json.loads((FOLDER/'short_side_open_acceptance.json').read_bytes())
    if (source['status']!='open_short_side_at_candidate_pending_inspection'
            or acceptance.get('accepted') is not True
            or acceptance.get('source_sha256')!=hashlib.sha256((FOLDER/'short_side_open_trial.json').read_bytes()).hexdigest()):
        raise RuntimeError('Completed open-jaw trial and operator fit acceptance required.')
    seat=source['final']['pose_mm'];lift=dict(seat,Z=round(seat['Z']+5,3))
    plan=dict(seat=seat,lift=lift,lift_speed=5,closure=closure_plan(28,25),
              holder_angle=source['plan']['geometry']['holder_angle'])
    print(json.dumps(plan),flush=True)
    if not args.execute:return
    path=FOLDER/'short_side_grip_lift_trial.json'
    record=dict(status='checking',plan=plan,steps=[],samples=[],grasp_accepted=False,
                operator_fit_acceptance=acceptance,force_settings_changed=False)
    with path.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def save():write_run_record(path,record)
    def check(pose,e1=None):
        s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
        if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
                or r.get('control_mode',{}).get('mode')!='auto'
                or r.get('program_state',{}).get('state')!='running'
                or s['sequence'].get('active') or not s['envelope']['enabled']
                or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual'))):
            raise RuntimeError('Controller not stationary healthy Auto; no recovery/retry.')
        near(r['pose_mm'],pose,.05)
        axes=n['external_axes']
        if not all(math.isfinite(axes[k]) for k in ('E1','E2')) or abs(axes['E2']-plan['holder_angle'])>.5:
            raise RuntimeError('Holder/axis feedback changed.')
        if e1 is not None and abs(axes['E1']-e1)>.07:raise RuntimeError('Jaw feedback changed.')
        record['samples'].append(dict(at=time.time(),pose=r['pose_mm'],axes=axes));save()
        return s,n
    try:
        # A read-only reconnect is allowed only before any motion is submitted.
        s=api('state');n=DragGoRPC('192.168.201.220').info()
        if s['sequence'].get('active') or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
            raise RuntimeError('Cannot prepare a connection in this state.')
        if not s['robot'].get('connected'):record['connection']=api('connect',{});save()
        s,n=check(seat,28)
        record['baseline']=api('gripper',{'action':'torque'});save()
        previous=28
        for command in plan['closure']['commands']:
            check(seat,previous)
            step=dict(phase='close',command=command,status='dispatching');record['steps'].append(step);save()
            result=api('gripper',dict(action='move',e1=command['target_e1_mm'],speed=command['speed']))
            step['response']=result;save()
            # Immediate contact hint is retained in the receipt; settling and
            # fresh position/torque feedback below decide completion.
            deadline=time.monotonic()+2;stable=0
            while stable<3:
                s,n=check(seat)
                stable=stable+1 if abs(n['external_axes']['E1']-command['target_e1_mm'])<=.07 else 0
                if time.monotonic()>deadline:raise RuntimeError('Jaw did not settle; no retry.')
                if stable<3:time.sleep(.1)
            torque=api('gripper',{'action':'torque'})
            if (not torque.get('telemetry_live') or not math.isfinite(torque['e1_torque'])
                    or abs(torque['e1_position']-command['target_e1_mm'])>.07):
                raise RuntimeError('Fresh grip telemetry not verified.')
            step.update(status='completed',actual=n['external_axes']['E1'],torque_report=torque);save()
            previous=command['target_e1_mm']
            print(json.dumps(dict(phase='close',e1=previous,torque=torque)),flush=True)
        for _ in range(3):check(seat,25);time.sleep(.15)
        s,n=check(seat,25)
        env={k:[s['envelope'][k]['min'],s['envelope'][k]['max']] for k in ('X','Y','Z')}
        check_path(seat,lift,s['robot']['joints'],api('robot_params'),env)
        step=dict(phase='proof_lift',target=lift,speed=5,status='dispatching');record['steps'].append(step);save()
        step['response']=api('move',dict(x=lift['X'],y=lift['Y'],z=lift['Z'],rz=lift['Rz'],speed=5,interpolation='linear'))
        s,n=check(lift,25)
        step.update(status='completed',final=s,final_native=n);save()
        record.update(status='proof_lift_completed_retention_pending',final=s,final_native=n)
        print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],axes=n['external_axes'])),flush=True)
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error))
        if any(step.get('status')=='dispatching' for step in record['steps']):
            try:record['stop_response']=api('seq/stop',{})
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();save()


if __name__=='__main__':main()
