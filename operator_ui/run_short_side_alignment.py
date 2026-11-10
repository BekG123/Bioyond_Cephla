"""Authorized empty Home return, open at Home, one pinned alignment queue."""
import json
import sys
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_alignment_trial import reference,FOLDER,PLAN_SHA

smooth='--smooth' in sys.argv
candidate='smooth_direct' if smooth else 'direct'
plan,taught=reference();path=FOLDER/('home_then_'+candidate+'_trial.json')
if path.exists():raise RuntimeError('Workflow already attempted; review before any retry')
record=dict(started_at=time.time(),status='preparing',plan_sha256=PLAN_SHA,actions=[],samples=[],
    authorization='Both paths and jaw opening clear; empty gripper, arm released, hands clear, E-stop supervised; run Home then taught direct approach.')
def save():path.write_text(json.dumps(record,indent=2))
def call(endpoint,body):
    response=api(endpoint,body);record['actions'].append(dict(endpoint=endpoint,response=response,at=time.time()));save()
    if not response.get('ok'):raise RuntimeError(str(response))
    return response
def native_check(e1=None):
    n=DragGoRPC('192.168.201.220').info()
    if any(n[k] for k in ('error','emergency','drag')):raise RuntimeError('Controller unhealthy; stop workflow')
    if abs(n['external_axes']['E2']-taught['e2_degrees'])>.1:raise RuntimeError('Holder changed from taught orientation')
    if e1 is not None and abs(n['external_axes']['E1']-e1)>.15:raise RuntimeError('Jaw position changed')
    return n
def wait(label,e1):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        seq=api('seq');native=native_check(e1)
        record['samples'].append(dict(label=label,at=time.time(),sequence_state=seq['state'],native=native));save()
        if not seq['active']:
            record[label+'_sequence']=seq;save()
            if seq['state']!='done' or not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq.get('result')))
            print(json.dumps(dict(stage=label,result=seq['result'])),flush=True)
            return
        time.sleep(.3)
    raise RuntimeError('Workflow timeout; inspect before retrying')

s=api('state');assert not s['sequence']['active']
if not s['robot'].get('connected'):
    assert api('connect',{'ip':'192.168.201.220'})['ok'];s=api('state')
r=s['robot']
assert r['ok'] and not r['errors']
if smooth:
    assert r['enabled'] and r['control_mode']['mode']=='auto' and r['program_state']['state']=='running' and r['lua_app_initialized']
else:
    assert not r['enabled'] and r['program_state']['state'] in ('paused','stopped')
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
near(r['pose_mm'],taught['target'],.1)
assert not native_check(28 if smooth else 0)['moving']
record['before']=s
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    # Stop the paused program before Auto; never resume the paused instruction.
    if not smooth:
        for endpoint,body in [('program',{'action':'stop'}),('mode',{'mode':'auto'}),('enable',{'confirm':True}),('program',{'action':'start'})]:
            call(endpoint,body)
    native_check(28 if smooth else 0);near(api('state')['robot']['pose_mm'],taught['target'],.1)
    proposed=call('researcher/api/lacry/button/move_home',{})['plan']
    if proposed['dispatch']!='ik_home_return':raise RuntimeError('Home planner selected a different route')
    near(proposed['start'],taught['target'],.1);near(proposed['home'],plan['home'],.01)
    stages=proposed['stages']
    if len(stages)!=6 or [s['kind'] for s in stages]!=['queue','rotate','rotate','rotate','rotate','queue']:
        raise RuntimeError('Home route differs from the confirmed preview')
    near(stages[0]['points'][0],dict(taught['target'],Z=300),.01)
    near(stages[-1]['points'][0],dict(plan['home'],Z=300),.01)
    near(stages[-1]['points'][-1],plan['home'],.01)
    call('researcher/api/lacry/confirm',dict(ready=True,plan_id=proposed['id']))
    wait('home',28 if smooth else 0)
    near(api('state')['robot']['pose_mm'],plan['home'],.1)
    if not smooth:call('gripper',dict(action='move',e1=28,speed=10))
    for _ in range(3):
        native_check(28);near(api('state')['robot']['pose_mm'],plan['home'],.1);time.sleep(.1)
    call('developer/api/holder/alignment-trial',dict(candidate=candidate,ready=True,empty_gripper=True,path_clear=True))
    wait('alignment',28)
    near(api('state')['robot']['pose_mm'],plan['goal'],.2)
    record.update(status='completed_awaiting_operator_inspection',finished_at=time.time())
    save();print(json.dumps(dict(status=record['status'],report=str(path))),flush=True)
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error),finished_at=time.time())
    try:
        if api('seq')['active']:record['stop_requested']=api('researcher/api/lacry/stop',{})
    except Exception as stop_error:record['stop_error']=str(stop_error)
    save();raise
