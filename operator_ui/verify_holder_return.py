"""Read-only reconciliation of a lost rotation reply; never resend movement."""
import hashlib
import json
import time
from proof_lift_plate import api, near
from draggo import DragGoRPC
from holder_rotation_trial import ROOT, HOME

path=ROOT/'return_original_verified.json'
if path.exists():raise RuntimeError('Verification already recorded')
raw=(ROOT/'return_original.json').read_bytes()
attempt=json.loads(raw)
target=attempt['target_degrees']
assert attempt['motion_sent']
probe=json.loads((ROOT/'direction_probe.json').read_text())
assert abs(target-probe['origin_degrees'])<1e-6
s=api('state');assert not s['sequence']['active']
if not s['robot'].get('connected'):
    assert api('connect',{'ip':'192.168.201.220'})['ok']
samples=[]
for _ in range(3):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    assert not s['sequence']['active'] and r['ok'] and not r['errors']
    assert r['enabled'] and r['program_state']['state']=='running' and r['control_mode']['mode']=='auto'
    assert not any(n[k] for k in ('moving','error','emergency','drag','manual'))
    assert abs(n['external_axes']['E2']-target)<.1
    near(r['pose_mm'],attempt['before']['robot']['pose_mm'],.1)
    near(r['pose_mm'],HOME,.2)
    for key,value in attempt['before']['native']['external_axes'].items():
        if key!='E2':assert abs(n['external_axes'][key]-value)<.05
    samples.append(dict(robot=r,native=n));time.sleep(.3)
record=dict(status='original_restored_by_readback',result={'ok':True},
    original_attempt_sha256=hashlib.sha256(raw).hexdigest(),
    target_degrees=target,after=samples[-1],samples=samples,
    controller_reply_received=False,motion_resent=False,at=time.time())
with path.open('x') as f:json.dump(record,f,indent=2)
print(json.dumps(dict(status=record['status'],actual_e2=samples[-1]['native']['external_axes']['E2'],report=str(path))))
