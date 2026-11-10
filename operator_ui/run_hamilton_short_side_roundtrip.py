"""Authorized empty site4 -> Home -> site4, no retry or gripper commands."""
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from hamilton_short_side_trial import reference,validate_route,FOLDER

plan,parent=reference();path=FOLDER/'hamilton_short_side_empty_roundtrip01.json'
if path.exists():raise RuntimeError('This roundtrip was already attempted; inspect its receipt')
record=dict(status='prepared',started_at=time.time(),actions=[],samples=[],payload='empty',
    authorization='Both direct paths and full sweep confirmed clear. Plate removed; jaws empty; hands clear; E-stop supervised.',
    speed=137,gripper_commands=[])
def save():path.write_text(json.dumps(record,indent=2))
def check():
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    if not r.get('ok') or not r.get('connected') or r.get('errors') or any(n[k] for k in ('error','emergency','drag')):raise RuntimeError('Unhealthy controller; no retry')
    if abs(n['external_axes']['E1'])>.15:raise RuntimeError('Unexpected jaw position')
    if 'initial_e2' in record and abs(n['external_axes']['E2']-record['initial_e2'])>.1:raise RuntimeError('Holder moved')
    record['samples'].append(dict(at=time.time(),state=s,native=n));return s,n
def call(ep,body):
    result=api(ep,body);record['actions'].append(dict(at=time.time(),endpoint=ep,response=result));save()
    if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):raise RuntimeError(str(result))
    return result
def wait(direction):
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        s,n=check();seq=api('seq');save()
        if not seq['active']:
            record[direction]=seq;save()
            if seq['state']!='done' or not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq.get('result')))
            near(s['robot']['pose_mm'],plan['routes'][direction]['points'][-1],.2)
            if n['moving']:raise RuntimeError('Controller not stationary after completion')
            print(json.dumps(dict(stage=direction,result=seq['result'])),flush=True);return
        time.sleep(.2)
    raise RuntimeError('Sequence timed out; stopping without retry')

s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:assert api('connect',{'ip':'192.168.201.220'})['ok']
s,n=check();r=s['robot'];record['initial_e2']=n['external_axes']['E2']
assert not s['sequence']['active'] and not n['moving'] and not r['enabled'] and r['program_state']['state'] in ('paused','stopped')
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
cfg=api('robot_params');env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
assert s['envelope']['enabled']
validate_route(r['pose_mm'],plan['routes']['reverse']['points'],r['joints'],cfg,env,'reverse')
validate_route(plan['start'],plan['routes']['forward']['points'],parent['home_joints'],cfg,env,'forward')
start=r['pose_mm']
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    for ep,body in [('program',{'action':'stop'}),('mode',{'mode':'auto'}),('enable',{'confirm':True}),('program',{'action':'start'})]:call(ep,body)
    s,n=check();near(s['robot']['pose_mm'],start,.1)
    print(json.dumps(dict(stage='empty_controller_prepared',pose=s['robot']['pose_mm'])),flush=True)
    for direction in ('reverse','forward'):
        s,n=check()
        validate_route(s['robot']['pose_mm'],plan['routes'][direction]['points'],s['robot']['joints'],cfg,env,direction)
        call('developer/api/hamilton-short-side-trial',dict(direction=direction,ready=True,empty_gripper=True,path_clear=True))
        wait(direction)
    s,n=check();record.update(status='completed_awaiting_operator_inspection',final_state=s)
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error))
    try:
        if api('seq')['active']:record['stop_response']=api('researcher/api/lacry/stop',{})
    except Exception as e:record['stop_error']=str(e)
    raise
finally:
    record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],report=str(path))))
