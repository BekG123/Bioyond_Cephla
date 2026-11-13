"""Prepare empty-arm Auto after publication; do not send a holder rotation."""
import json
from proof_lift_plate import api, near
from holder_rotation_trial import ROOT, HOME
from draggo import DragGoRPC

path=ROOT/'fast137_startup.json'
if path.exists():raise RuntimeError('Startup already attempted; inspect before retrying')
s=api('state')
assert not s['sequence']['active']
if not s['robot'].get('connected'):
    assert api('connect',{'ip':'192.168.201.220'})['ok']
    s=api('state')
r=s['robot']
assert r['ok'] and not r['errors'] and r['program_state']['state']=='stopped'
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
near(r['pose_mm'],HOME,.2)
n=DragGoRPC('192.168.201.220').info()
assert not any(n[k] for k in ('moving','error','emergency','drag'))
assert abs(n['external_axes']['E1'])<.5
record=dict(before=s,native=n,actions=[],authorization='Published; test speed 137. Empty gripper and retained plate confirmed; supervised clear holder sweep.')
with path.open('x') as f:json.dump(record,f,indent=2)
def save():path.write_text(json.dumps(record,indent=2))
try:
    for endpoint,body in [('mode',{'mode':'auto'}),('enable',{'confirm':True}),('program',{'action':'start'})]:
        answer=api(endpoint,body);record['actions'].append(dict(endpoint=endpoint,response=answer));save()
        if not answer.get('ok'):raise RuntimeError(str(answer))
    record['after']=api('state')
    record['after_native']=DragGoRPC('192.168.201.220').info()
    near(record['after']['robot']['pose_mm'],HOME,.2)
    save();print(json.dumps(record['after_native'],indent=2))
except Exception as error:
    record['error']=str(error);save();raise
