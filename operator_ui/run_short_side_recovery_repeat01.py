"""Authorized empty startup -> Home -> restore holder -> accepted alignment."""
import json
import time
import sys
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_alignment_trial import reference,FOLDER
from researcher_home import queued_station_stages

resume='--resume-after-no-motion' in sys.argv
plan,taught=reference();path=FOLDER/('home_restore_smooth_resume01.json' if resume else 'recovery_home_smooth_repeat01.json')
if path.exists():raise RuntimeError('Repeat already attempted; inspect evidence before retrying')
start=dict(X=304.273,Y=-63.19,Z=184.038,Rz=44.305)
if resume:
    prior=json.loads((FOLDER/'restore_taught_angle_repeat01.json').read_bytes())
    assert prior.get('motion_sent') is False and prior.get('error')=='Stopped before holder restore'
    start=plan['home']
record=dict(status='prepared',at=time.time(),actions=[],samples=[],
    authorization='Operator confirmed empty jaws, seated plate, lift/wrist/Home route and holder adjustment clear, arm released and E-stop supervised; restore holder and run.')
def save():path.write_text(json.dumps(record,indent=2))
def check(e1=None,restored=False):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    if not r.get('ok') or not r.get('connected') or r.get('errors') or any(n[k] for k in ('error','emergency','drag')):raise RuntimeError('Controller unhealthy; no retry')
    if abs(n['external_axes']['E2']-taught['e2_degrees'])>(.1 if restored else .5):raise RuntimeError('Holder moved beyond reviewed correction')
    if e1 is not None and abs(n['external_axes']['E1']-e1)>.15:raise RuntimeError('Jaw position changed')
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    return s,n
def call(endpoint,body):
    r=api(endpoint,body);record['actions'].append(dict(at=time.time(),endpoint=endpoint,response=r));save()
    if not r.get('ok'):raise RuntimeError(str(r))
    return r
def wait(label,e1,restored=False):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        s,n=check(e1,restored);seq=api('seq');save()
        if not seq['active']:
            record[label]=seq;save()
            if seq['state']!='done' or not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq))
            print(json.dumps(dict(stage=label,result=seq['result'])),flush=True);return
        time.sleep(.25)
    raise RuntimeError('Timed out; inspect before retrying')

s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok']
s,n=check(0);r=s['robot']
assert not n['moving'] and not s['sequence']['active']
if resume:assert r['enabled'] and r['control_mode']['mode']=='auto' and r['program_state']['state']=='running'
else:assert not r['enabled'] and r['program_state']['state']=='stopped'
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
near(r['pose_mm'],start,.1)
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    if not resume:
        for ep,body in [('mode',{'mode':'auto'}),('enable',{'confirm':True}),('program',{'action':'start'})]:call(ep,body)
    s,n=check(0);near(s['robot']['pose_mm'],start,.1)
    if resume:
        proposed=dict(dispatch='ik_home_return',start=plan['home'],home=plan['home'],stages=[])
    else:proposed=call('researcher/api/lacry/button/move_home',{})['plan']
    if proposed['dispatch']!='ik_home_return':raise RuntimeError('Unexpected Home route')
    near(proposed['start'],start,.1);near(proposed['home'],plan['home'],.01)
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    expected=queued_station_stages(proposed['start'],plan['home'],s['robot']['joints'],api('robot_params'),env)
    if len(proposed['stages'])!=len(expected):raise RuntimeError('Home route changed')
    for a,b in zip(proposed['stages'],expected):
        if a['kind']!=b['kind']:raise RuntimeError('Home stage changed')
        if a['kind']=='rotate':
            if abs(a['rz']-b['rz'])>.02:raise RuntimeError('Home wrist target changed')
        else:
            if len(a['points'])!=len(b['points']):raise RuntimeError('Home queue changed')
            for x,y in zip(a['points'],b['points']):near(x,y,.02)
    if not resume:
        call('researcher/api/lacry/confirm',dict(ready=True,plan_id=proposed['id']))
        wait('home',0)
    near(api('state')['robot']['pose_mm'],plan['home'],.1)
    call('developer/api/holder/restore-taught-angle',dict(ready=True,empty_gripper=True,holder_clear=True))
    wait('holder_restore',0,False)
    check(0,True)
    call('gripper',dict(action='move',e1=28,speed=10))
    for _ in range(3):
        s,n=check(28,True);near(s['robot']['pose_mm'],plan['home'],.1);time.sleep(.1)
    call('developer/api/holder/alignment-trial',dict(candidate='smooth_repeat01',ready=True,empty_gripper=True,path_clear=True))
    wait('alignment',28,True)
    s,n=check(28,True);near(s['robot']['pose_mm'],plan['goal'],.2)
    if n['moving']:raise RuntimeError('Arm not stationary')
    record.update(status='completed_above_plate',final_state=s)
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error))
    try:
        if api('seq')['active']:record['stop_response']=api('researcher/api/lacry/stop',{})
    except Exception as e:record['stop_error']=str(e)
    raise
finally:record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],report=str(path))))
