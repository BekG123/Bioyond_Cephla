"""Empty Home return then corrected alignment plus 30 mm descent at 137."""
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_alignment_trial import reference_for_candidate,FOLDER,validate_route,candidate_points
from researcher_home import queued_station_stages

plan,taught=reference_for_candidate('corrected02')
path=FOLDER/'home_corrected02_descent_trial.json'
if path.exists():raise RuntimeError('Trial already attempted; preserve evidence before retrying')
record=dict(status='prepared',at=time.time(),actions=[],samples=[],
    authorization='Operator saved corrected ideal and 30 mm descent at speed 137, then requested Home and retry the new sequence.',
    grip_requested=False)
def save():path.write_text(json.dumps(record,indent=2))
def check(e1=None):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    if not r.get('ok') or not r.get('connected') or r.get('errors') or any(n[k] for k in ('error','emergency','drag')):raise RuntimeError('Unhealthy controller; no retry')
    if abs(n['external_axes']['E2']-taught['e2_degrees'])>.1:raise RuntimeError('Holder differs from corrected teaching')
    if e1 is not None and abs(n['external_axes']['E1']-e1)>.15:raise RuntimeError('Jaw position changed')
    record['samples'].append(dict(at=time.time(),state=s,native=n));return s,n
def call(ep,body):
    result=api(ep,body);record['actions'].append(dict(at=time.time(),endpoint=ep,response=result));save()
    if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):raise RuntimeError(str(result))
    return result
def wait(label,e1):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        s,n=check(e1);seq=api('seq');save()
        if not seq['active']:
            record[label]=seq;save()
            if seq['state']!='done' or not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq.get('result')))
            print(json.dumps(dict(stage=label,result=seq['result'])),flush=True);return
        time.sleep(.25)
    raise RuntimeError('Sequence timed out; no retry')

s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok']
s,n=check(0);r=s['robot'];start=taught['target']
assert not s['sequence']['active'] and not n['moving'] and not r['enabled'] and r['program_state']['state'] in ('paused','stopped')
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
near(r['pose_mm'],start,.1)
cfg=api('robot_params');env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
assert s['envelope']['enabled']
record['home_preview']=queued_station_stages(r['pose_mm'],plan['home'],r['joints'],cfg,env)
validate_route(plan['home'],candidate_points(plan,'corrected02'),plan['home_joints'],cfg,env,'corrected02')
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    # Discard paused instructions before starting the empty-gripper controller.
    for ep,body in [('program',{'action':'stop'}),('mode',{'mode':'auto'}),('enable',{'confirm':True}),('program',{'action':'start'})]:call(ep,body)
    s,n=check(0);near(s['robot']['pose_mm'],start,.1)
    proposed=call('researcher/api/lacry/button/move_home',{})['plan']
    if proposed['dispatch']!='ik_home_return':raise RuntimeError('Unexpected Home route')
    near(proposed['start'],start,.1);near(proposed['home'],plan['home'],.01)
    expected=queued_station_stages(proposed['start'],plan['home'],s['robot']['joints'],cfg,env)
    if len(proposed['stages'])!=len(expected):raise RuntimeError('Home stages changed')
    for a,b in zip(proposed['stages'],expected):
        if a['kind']!=b['kind']:raise RuntimeError('Home stage changed')
        if a['kind']=='rotate':
            if abs(a['rz']-b['rz'])>.02:raise RuntimeError('Home rotation changed')
        else:
            if len(a['points'])!=len(b['points']):raise RuntimeError('Home queue changed')
            for x,y in zip(a['points'],b['points']):near(x,y,.02)
    call('researcher/api/lacry/confirm',dict(ready=True,plan_id=proposed['id']));wait('home',0)
    near(api('state')['robot']['pose_mm'],plan['home'],.1)
    call('gripper',dict(action='move',e1=28,speed=10))
    for _ in range(3):
        s,n=check(28);near(s['robot']['pose_mm'],plan['home'],.1);time.sleep(.1)
    call('developer/api/holder/alignment-trial',dict(candidate='corrected02',ready=True,empty_gripper=True,path_clear=True))
    wait('approach_and_descent',28)
    for _ in range(3):
        s,n=check(28);near(s['robot']['pose_mm'],plan['goal'],.2);time.sleep(.2)
    if n['moving']:raise RuntimeError('Arm still moving')
    record.update(status='completed_awaiting_operator_inspection',final_state=s)
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error))
    try:
        if api('seq')['active']:record['stop_response']=api('researcher/api/lacry/stop',{})
    except Exception as e:record['stop_error']=str(e)
    raise
finally:record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],report=str(path))))
