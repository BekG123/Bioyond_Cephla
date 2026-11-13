"""Authorized empty-arm startup and one logged slow holder direction test."""
import json
import time
from pathlib import Path
from proof_lift_plate import api, near
from draggo import DragGoRPC
from holder_rotation_trial import HOME, ROOT

ROOT.mkdir(parents=True, exist_ok=True)
receipt = ROOT/'probe_startup.json'
if receipt.exists() or (ROOT/'direction_probe.json').exists():
    raise RuntimeError('Trial already attempted; inspect outcome, do not retry.')
s = api('state')
assert not s['sequence']['active']
if not s['robot'].get('connected'):
    assert api('connect', {'ip':'192.168.201.220'})['ok']
    s = api('state')
r = s['robot']
assert r['ok'] and not r['errors'] and r['program_state']['state']=='stopped'
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
near(r['pose_mm'],HOME,.2)
n=DragGoRPC('192.168.201.220').info()
assert not any(n[k] for k in ('moving','error','emergency','drag'))
assert abs(n['external_axes']['E1'])<.5
record=dict(before=s,native=n,authorization='Operator confirmed empty jaws, plate flat in holder, full rotation clear, hands clear and supervised E-stop; published and asked to continue.',actions=[])
with receipt.open('x') as f:json.dump(record,f,indent=2)
def save():receipt.write_text(json.dumps(record,indent=2))
try:
    for endpoint,body in [('mode',{'mode':'auto'}),('enable',{'confirm':True}),('program',{'action':'start'})]:
        answer=api(endpoint,body)
        record['actions'].append(dict(endpoint=endpoint,response=answer));save()
        if not answer.get('ok'):raise RuntimeError(str(answer))
    near(api('state')['robot']['pose_mm'],HOME,.2)
    answer=api('developer/api/holder/direction-probe',{'ready':True,'empty_gripper':True,'holder_clear':True})
    record['start']=answer;save()
    if not answer.get('ok'):raise RuntimeError(str(answer))
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        seq=api('seq')
        if not seq['active']:
            record['completion']=seq;save()
            print(json.dumps(seq,indent=2))
            break
        time.sleep(.3)
    else:
        record['stop']=api('program',{'action':'stop'});save()
        raise RuntimeError('Probe timeout; stop requested, no retry.')
except Exception as e:
    record['error']=str(e);save();raise
