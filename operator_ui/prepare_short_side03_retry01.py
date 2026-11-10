"""One operator-confirmed empty restart and Home return after plate reseating."""
import json
import argparse
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_full_trial import receipt,reference

path=receipt('preparation','03','retry01')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--resume-after-start',action='store_true')
parser.add_argument('--resume-home-preview',action='store_true')
args=parser.parse_args();resume=args.resume_after_start or args.resume_home_preview
initial_e1=0.0
if resume:
    previous=json.loads(path.read_bytes())
    assert previous['status']=='failed_or_uncertain' and 'home_plan' not in previous
    a=previous['actions'][-1]
    assert a['endpoint']=='program' and a['body']['action']=='start' and a['response']['ok']
    initial_e1=a['response']['gripper_after_start']['e1_position']
    assert 24.8<initial_e1<25.2
    path=receipt('preparation_complete','03','retry01')
    if args.resume_home_preview:
        preview=json.loads(path.read_bytes())
        assert preview['status']=='failed_or_uncertain'
        assert all(a['endpoint']!='researcher/api/lacry/confirm' for a in preview['actions'])
        assert preview['actions'][-1]['endpoint']=='researcher/api/lacry/button/move_home'
        path=receipt('preparation_verified','03','retry01')
if path.exists():raise RuntimeError('Preparation already attempted; inspect its record')
prior=json.loads(receipt('outcome','03').read_bytes())
assert prior['status']=='stopped_during_proof_lift' and prior['hamilton_motion_started'] is False
p,parent,grip=reference('03')
expected=dict(X=306.176,Y=-62.879,Z=76.723,Rz=87.803)
record=dict(status='started',started_at=time.time(),operator_confirmed_plate_reseated_empty_jaws=True,
    authorization='After partial lift, operator removed and reseated plate, confirmed empty jaws/hands clear/E-stop supervised and requested continue. Existing Home and new Hamilton routes remain authorized.',
    prior_outcome=str(receipt('outcome','03')),actions=[],samples=[])
def save():path.write_text(json.dumps(record,indent=2))
def read(ready=False):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    assert r.get('ok') and r.get('connected') and not r.get('errors')
    assert not any(n[k] for k in ('manual','drag','emergency','error'))
    assert abs(n['external_axes']['E2']-grip['holder_e2_degrees'])<.1
    if ready:
        assert r['enabled'] and r['program_state']['state']=='running'
        assert abs(n['external_axes']['E1']-initial_e1)<.15
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    return s,n
def call(endpoint,body):
    a=dict(at=time.time(),endpoint=endpoint,body=body);record['actions'].append(a);save()
    a['response']=api(endpoint,body);save()
    assert a['response'].get('ok'),a['response']
    return a['response']
s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:assert api('connect',{'ip':'192.168.201.220'})['ok']
for _ in range(3):
    s,n=read();near(s['robot']['pose_mm'],expected,.1)
    assert not s['sequence']['active'] and not n['moving']
    assert 24.8<n['external_axes']['E1']<25.2
    assert s['robot']['program_state']['state']==('running' if resume else 'stopped')
    time.sleep(.2)
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    if resume:assert s['robot']['enabled']
    elif not s['robot']['enabled']:call('enable',{'confirm':True})
    # Explicit operator removal confirmation supersedes cached held-object data.
    # Uses existing startup API once; no guards removed, no fault clear or resume.
    if not resume:
        result=call('program',{'action':'start','force':True})
        initial_e1=result['gripper_after_start']['e1_position']
    record['jaw_position_preserved_mm']=initial_e1
    record['continued_after_verified_startup']=resume
    s,n=read(True);near(s['robot']['pose_mm'],expected,.1);assert not n['moving']
    proposal=call('researcher/api/lacry/button/move_home',{})['plan']
    assert proposal['dispatch']=='ik_home_return'
    near(proposal['start'],s['robot']['pose_mm'],.05);near(proposal['home'],parent['home'],.01)
    stages=proposal['stages']
    assert 3<=len(stages)<=6 and stages[0]['kind']=='queue' and stages[-1]['kind']=='queue'
    assert all(stage['kind']=='rotate' for stage in stages[1:-1])
    assert len(stages[0]['points'])==1 and len(stages[-1]['points'])==2
    near(stages[0]['points'][0],dict(expected,Z=300),.1)
    last_yaw=proposal['start']['Rz']
    for stage in stages[1:-1]:
        assert parent['home']['Rz']-.01<=stage['rz']<last_yaw and last_yaw-stage['rz']<=25.01
        last_yaw=stage['rz']
    assert abs(last_yaw-parent['home']['Rz'])<.01
    near(stages[-1]['points'][0],dict(parent['home'],Z=300),.01)
    near(stages[-1]['points'][1],parent['home'],.01)
    record['home_plan']=proposal;save()
    call('researcher/api/lacry/confirm',{'ready':True,'plan_id':proposal['id']})
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        s,n=read(True);seq=api('seq');save()
        if not seq['active']:
            assert seq['state']=='done' and seq['result'].get('ok'),seq
            near(s['robot']['pose_mm'],parent['home'],.1);assert not n['moving']
            record.update(status='completed',final_state=s,final_sequence=seq);break
        time.sleep(.2)
    else:raise RuntimeError('Home timed out')
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error))
    if api('seq')['active']:record['stop_response']=api('researcher/api/lacry/stop',{})
    raise
finally:record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],report=str(path))))
