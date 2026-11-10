"""One loaded reverse-entry departure, then the existing IK Home return."""
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_full_trial import receipt,reference

p,parent,grip=reference('04');path=receipt('return_home','04')
if path.exists():raise RuntimeError('Return already attempted; inspect evidence')
planned=json.loads(receipt('return_plan','04').read_bytes())
record=dict(status='started',at=time.time(),actions=[],samples=[],gripper_commands=[],
    operator_authorized=True,program_restart_allowed=False,operator_retention_observation='pending')
def save():path.write_text(json.dumps(record,indent=2))
def check(stationary=False):
    s=api('state');n=DragGoRPC('192.168.201.220').info();r=s['robot']
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    assert r.get('ok') and r.get('connected') and not r.get('errors')
    assert r['enabled'] and r['program_state']['state']=='running' and r['control_mode']['mode']=='auto'
    assert not any(n[k] for k in ('manual','drag','error','emergency'))
    assert abs(n['external_axes']['E1']-25)<.07
    if stationary:assert not n['moving']
    return s,n
def call(ep,body):
    a=dict(at=time.time(),endpoint=ep,body=body);record['actions'].append(a);save()
    a['response']=api(ep,body);save();assert a['response'].get('ok'),a['response']
    return a['response']
def wait(label):
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        s,n=check();seq=api('seq');save()
        if not seq['active']:
            assert seq['state']=='done' and seq['result'].get('ok'),seq
            s,n=check(True);record[label]=seq;save()
            return s,n
        time.sleep(.2)
    raise RuntimeError('Return timed out')
s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:assert api('connect',{'ip':'192.168.201.220'})['ok']
s,n=check(True);assert not s['sequence']['active']
near(s['robot']['pose_mm'],p['routes']['departure']['start'],.1)
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
with path.open('x') as stream:json.dump(record,stream,indent=2)
try:
    call('developer/api/short-side-full-trial04',dict(phase='departure',ready=True,setup_confirmed=True,path_clear=True))
    s,n=wait('departure');near(s['robot']['pose_mm'],p['taught_turn'],.1)
    print(json.dumps(dict(stage='clear_of_hamilton',pose=s['robot']['pose_mm'])),flush=True)
    home=call('researcher/api/lacry/button/move_home',{})['plan']
    assert home['dispatch']=='ik_home_return' and home['preserve_gripper'] is True
    near(home['start'],s['robot']['pose_mm'],.05);near(home['home'],parent['home'],.01)
    assert len(home['stages'])==len(planned['home_stages'])
    for actual,expected in zip(home['stages'],planned['home_stages']):
        assert actual['kind']==expected['kind']
        if actual['kind']=='rotate':assert abs(actual['rz']-expected['rz'])<.1
        else:
            assert len(actual['points'])==len(expected['points'])
            for a,e in zip(actual['points'],expected['points']):near(a,e,.1)
    record['home_plan']=home;save()
    call('researcher/api/lacry/confirm',dict(ready=True,plan_id=home['id']))
    s,n=wait('home');near(s['robot']['pose_mm'],parent['home'],.1)
    record.update(status='completed_awaiting_operator_inspection',final_state=s,final_native=n)
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error))
    if api('seq')['active']:record['stop_response']=api('researcher/api/lacry/stop',{})
    raise
finally:record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],report=str(path))))
