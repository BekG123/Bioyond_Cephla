"""Nonmoving reload at a healthy stationary loaded endpoint; no startup."""
import json
import subprocess
import time
from pathlib import Path
import psutil
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_full_trial import reference,FOLDER,receipt

root=Path(__file__).resolve().parents[1];p,_,_=reference('04')
assert json.loads(receipt('operator_acceptance','04').read_bytes())['accepted']
target=p['routes']['reverse']['start']
def check():
    s=api('state');n=DragGoRPC('192.168.201.220').info();r=s['robot']
    assert not s['sequence']['active'] and r.get('ok') and r.get('connected') and not r.get('errors')
    assert r['enabled'] and r['program_state']['state']=='running'
    assert not any(n[k] for k in ('moving','error','emergency','drag','manual'))
    assert abs(n['external_axes']['E1']-25)<.07
    near(r['pose_mm'],target,.1)
    return dict(state=s,native=n)
s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:assert api('connect',{'ip':'192.168.201.220'})['ok']
before=check();time.sleep(.3);check()
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
listeners=[c for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002]
assert len({c.pid for c in listeners})==1
process=psutil.Process(listeners[0].pid);assert 'operator_ui/app.py' in process.cmdline();env=process.environ()
folder=FOLDER/'reload_full_sequence04_return';folder.mkdir(exist_ok=False)
(folder/'before.json').write_text(json.dumps(before,indent=2))
assert api('camera/release',{})['ok'];assert api('disconnect',{})['ok']
process.terminate();process.wait(10)
with (folder/'stdout.log').open('w') as out,(folder/'stderr.log').open('w') as err:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],cwd=root,env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
deadline=time.monotonic()+20
while time.monotonic()<deadline:
    try:api('state');break
    except Exception:time.sleep(.3)
assert api('connect',{'ip':'192.168.201.220'})['ok']
after=check();(folder/'after.json').write_text(json.dumps(after,indent=2))
print(json.dumps(dict(reloaded=True,pid=child.pid,motion_started=False,gripper_preserved=True)))
