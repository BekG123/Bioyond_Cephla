"""Confirmed empty restart/Home before the phase-aware holder-monitor trial."""
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_full_trial import receipt,reference

path=receipt('ready','03','retry02')
if path.exists():raise RuntimeError('Attempt already prepared or failed; inspect its log')
old=json.loads(receipt('run','03','retry01').read_bytes())
assert old['status']=='failed_or_uncertain' and old['error']=='Holder changed'
assert not receipt('hamilton','03','retry01').exists()
p,parent,grip=reference('03')
expected=dict(X=306.009,Y=-62.903,Z=121.399,Rz=87.978)
record=dict(status='started',started_at=time.time(),actions=[],samples=[],
    operator_confirmed_plate_reseated_empty_jaws=True,
    authorization='Operator confirmed plate flat in rotated holder, jaws empty, hands clear, E-stop supervised and requested whole-sequence retry. Existing Home and new overhead Hamilton paths remain authorized.',
    monitor_policy='Holder reference required at stationary setup and through gripping; logged only during proof lift and loaded transport. Existing Lacry Home monitors unchanged.')
def save():path.write_text(json.dumps(record,indent=2))
def read(stationary=False):
    s=api('state');n=DragGoRPC('192.168.201.220').info();r=s['robot']
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    assert r.get('ok') and r.get('connected') and not r.get('errors')
    assert not any(n[k] for k in ('manual','drag','emergency','error'))
    if stationary:
        assert not n['moving'] and abs(n['external_axes']['E2']-grip['holder_e2_degrees'])<.1
    return s,n
def call(ep,body):
    a=dict(at=time.time(),endpoint=ep,body=body);record['actions'].append(a);save()
    a['response']=api(ep,body);save();assert a['response'].get('ok'),a['response']
    return a['response']
s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:assert api('connect',{'ip':'192.168.201.220'})['ok']
for _ in range(3):
    s,n=read(True);near(s['robot']['pose_mm'],expected,.2)
    assert not s['sequence']['active'] and -.15<=n['external_axes']['E1']<=28.15
    assert s['robot']['program_state']['state'] in ('stopped','running')
    time.sleep(.2)
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    if not s['robot']['enabled']:call('enable',{'confirm':True})
    if s['robot']['program_state']['state']=='stopped':
        # Current operator-confirmed plate removal resolves the stale grip cache.
        call('program',{'action':'start','force':True})
    s,n=read(True);near(s['robot']['pose_mm'],expected,.2)
    assert s['robot']['enabled'] and s['robot']['program_state']['state']=='running'
    e1=n['external_axes']['E1'];assert -.15<=e1<=28.15
    record['jaw_position_preserved_mm']=e1
    plan=call('researcher/api/lacry/button/move_home',{})['plan']
    assert plan['dispatch']=='ik_home_return'
    near(plan['start'],s['robot']['pose_mm'],.05);near(plan['home'],parent['home'],.01)
    stages=plan['stages'];assert 3<=len(stages)<=6
    assert stages[0]['kind']=='queue' and len(stages[0]['points'])==1
    assert stages[-1]['kind']=='queue' and len(stages[-1]['points'])==2
    near(stages[0]['points'][0],dict(plan['start'],Z=300),.01)
    last=plan['start']['Rz']
    for stage in stages[1:-1]:
        assert stage['kind']=='rotate' and parent['home']['Rz']-.01<=stage['rz']<last and last-stage['rz']<=25.01
        last=stage['rz']
    assert abs(last-parent['home']['Rz'])<.01
    near(stages[-1]['points'][0],dict(parent['home'],Z=300),.01)
    near(stages[-1]['points'][1],parent['home'],.01)
    record['home_plan']=plan;save()
    call('researcher/api/lacry/confirm',{'ready':True,'plan_id':plan['id']})
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        s,n=read();seq=api('seq');save()
        assert abs(n['external_axes']['E1']-e1)<.15
        if not seq['active']:
            assert seq['state']=='done' and seq['result'].get('ok'),seq
            s,n=read(True);near(s['robot']['pose_mm'],parent['home'],.1)
            record.update(status='completed',final_state=s,final_sequence=seq);break
        time.sleep(.2)
    else:raise RuntimeError('Home timed out')
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error))
    if api('seq')['active']:record['stop_response']=api('researcher/api/lacry/stop',{})
    raise
finally:record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],report=str(path))))
