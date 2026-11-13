"""Load repeat record IDs while the held arm is stationary; never start hardware."""
import json
import subprocess
import time
from pathlib import Path
import psutil
from proof_lift_plate import api, near
from draggo import DragGoRPC

root=Path(__file__).resolve().parents[1]
s=api('state')
if not s['robot'].get('connected'):
    assert not s['sequence']['active']
    assert api('connect',{'ip':'192.168.201.220'})['ok']
    s=api('state')
r=s['robot']
assert r['ok'] and not r['errors'] and not s['sequence']['active']
assert r['program_state']['state']=='running' and r['control_mode']['mode']=='auto'
near(r['pose_mm'],dict(X=186.42,Y=-366.27,Z=45.2,Rz=-1.1),.05)
assert abs(r['external_axes']['E1']-3.9)<.15
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
n=DragGoRPC('192.168.201.220').info()
assert not any(n[k] for k in ('moving','error','emergency','drag'))
time.sleep(.5)
second=api('state')
assert not second['sequence']['active']
near(second['robot']['pose_mm'],r['pose_mm'],.05)
assert abs(second['robot']['external_axes']['E1']-r['external_axes']['E1'])<.05
listeners=[c for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002]
assert len({c.pid for c in listeners})==1
p=psutil.Process(listeners[0].pid)
assert 'operator_ui/app.py' in p.cmdline()
env=p.environ()
folder=root/'operator_ui/reports/hamilton_repeat_ids_reload_20261109'
folder.mkdir(exist_ok=False)
(folder/'before.json').write_text(json.dumps(s,indent=2))
assert api('camera/release',{})['ok']
assert api('disconnect',{})['ok']
p.terminate();p.wait(10)
with (folder/'stdout.log').open('w') as stdout,(folder/'stderr.log').open('w') as stderr:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],cwd=root,env=env,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps(dict(reloaded=True,pid=child.pid,motion_started=False)))
