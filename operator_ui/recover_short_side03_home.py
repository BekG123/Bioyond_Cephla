"""Reviewed empty Home recovery using the existing Lacry recovery executor.

The earlier custom helper stopped travel on E2, an unrelated fixture axis.
Keep Lacry's existing arm/joint/corridor monitors; log E2 and check it at rest.
"""
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_full_trial import receipt,reference

path=receipt('ready','03','retry01')
if path.exists():raise RuntimeError('Recovery already attempted; inspect evidence')
_,parent,grip=reference('03')
prior=json.loads(receipt('preparation_verified','03','retry01').read_bytes())
assert prior['status']=='failed_or_uncertain' and prior['stop_response']['ok']
expected=dict(X=306.173,Y=-62.879,Z=120.481,Rz=87.801)
record=dict(status='started',started_at=time.time(),actions=[],samples=[],
    operator_confirmed_plate_reseated_empty_jaws=True,
    authorization='Operator confirmed plate reseated and jaws empty, hands clear, E-stop supervised, and requested continue after the helper stopped Home. Previously confirmed vertical/wrist/Home route remains clear.',
    prior_failure=str(receipt('preparation_verified','03','retry01')))
def save():path.write_text(json.dumps(record,indent=2))
def read(stationary=False):
    s=api('state');n=DragGoRPC('192.168.201.220').info();r=s['robot']
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    assert r.get('ok') and r.get('connected') and not r.get('errors')
    assert not any(n[k] for k in ('manual','drag','error','emergency'))
    if stationary:
        assert not n['moving']
        assert abs(n['external_axes']['E2']-grip['holder_e2_degrees'])<.1
    return s,n
def call(ep,body):
    a=dict(at=time.time(),endpoint=ep,body=body);record['actions'].append(a);save()
    a['response']=api(ep,body);save();assert a['response'].get('ok'),a['response']
    return a['response']
s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:assert api('connect',{'ip':'192.168.201.220'})['ok']
s,n=read(True);near(s['robot']['pose_mm'],expected,.1)
assert not s['sequence']['active'] and not api('researcher/api/lacry/state')['running']['active']
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert s['robot']['program_state']['state'] in ('stopped','running') and s['robot']['enabled']
assert abs(n['external_axes']['E1']-25.105)<.15
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    # Normal startup only; last live report showed empty-jaw torque -7.2.
    if s['robot']['program_state']['state']=='stopped':call('program',{'action':'start'})
    s,n=read(True);near(s['robot']['pose_mm'],expected,.1)
    assert s['robot']['program_state']['state']=='running'
    # At Z120.48, the operator-confirmed empty jaws are above the plate.
    call('gripper',{'action':'move','e1':0,'speed':5})
    s,n=read(True);near(s['robot']['pose_mm'],expected,.1);assert abs(n['external_axes']['E1'])<.1
    call('program',{'action':'stop'});call('disable',{})
    p=call('developer/api/home/recovery/preview',{})['plan']
    near(p['start'],expected,.1);near(p['home'],parent['home'],.01)
    stages=p['stages'];assert 3<=len(stages)<=6
    assert stages[0]['kind']=='queue' and stages[-1]['kind']=='queue'
    assert len(stages[0]['points'])==1 and len(stages[-1]['points'])==2
    near(stages[0]['points'][0],dict(expected,Z=300),.1)
    last=p['start']['Rz']
    for st in stages[1:-1]:
        assert st['kind']=='rotate' and parent['home']['Rz']-.01<=st['rz']<last and last-st['rz']<=25.01
        last=st['rz']
    assert abs(last-parent['home']['Rz'])<.01
    near(stages[-1]['points'][0],dict(parent['home'],Z=300),.01)
    near(stages[-1]['points'][1],parent['home'],.01)
    record['recovery_plan']=p;save()
    call('developer/api/home/recovery/confirm',dict(plan_id=p['id'],ready=True,empty_gripper=True,cell_clear=True,
        operator_checked_recovery=True,reviewed_failure=True,
        review_notes='Custom helper requested Stop during initial vertical lift on fixture-E2 transient. No controller collision errors. Operator removed/reseated plate and confirmed empty jaws and continued clear Home route. Actual stopped pose independently verified. Use unchanged Lacry monitored Home executor; keep historical failed motion record.'))
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        s,n=read();seq=api('seq');save()
        if abs(n['external_axes']['E1'])>.15:raise RuntimeError('Empty jaw position changed')
        if not seq['active']:
            assert seq['state']=='done' and seq['result'].get('ok'),seq
            s,n=read(True);near(s['robot']['pose_mm'],parent['home'],.1)
            record.update(status='completed',final_state=s,final_sequence=seq,jaw_position_preserved_mm=n['external_axes']['E1']);break
        time.sleep(.2)
    else:raise RuntimeError('Home recovery timed out')
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error))
    if api('seq')['active']:record['stop_response']=api('researcher/api/lacry/stop',{})
    raise
finally:record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],report=str(path))))
