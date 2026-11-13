"""Reload idle Home console to select fresh Hamilton trial output; no motion."""
import json
import subprocess
import time
from pathlib import Path
import psutil
from proof_lift_plate import api, near
from draggo import DragGoRPC

root = Path(__file__).resolve().parents[1]
state = api('state')
if not state['robot'].get('connected'):
    assert not state['sequence']['active']
    assert api('connect', {'ip':'192.168.201.220'})['ok']
    state = api('state')
r = state['robot']
assert r['ok'] and not r['errors'] and not state['sequence']['active']
assert r['program_state']['state'] == 'running' and r['control_mode']['mode'] == 'auto'
near(r['pose_mm'], dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88), .05)
assert abs(r['external_axes']['E1']-7)<.15
assert api('researcher/api/status')['hand_guiding']['state'] == 'off'
assert not api('researcher/api/lacry/state')['running']['active']
native = DragGoRPC('192.168.201.220').info()
assert not any(native[k] for k in ('moving','error','emergency','drag'))
time.sleep(.5)
second = api('state')
assert not second['sequence']['active']
near(second['robot']['pose_mm'], r['pose_mm'], .05)
listeners = [c for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002]
assert len({c.pid for c in listeners})==1
p = psutil.Process(listeners[0].pid)
assert 'operator_ui/app.py' in p.cmdline()
env=p.environ()
folder=root/'operator_ui/reports/hamilton_receipt_reload_repeat02_20261109'
folder.mkdir(exist_ok=False)
(folder/'before.json').write_text(json.dumps(state,indent=2))
assert api('camera/release',{})['ok']
assert api('disconnect',{})['ok']
p.terminate();p.wait(10)
with (folder/'stdout.log').open('w') as stdout, (folder/'stderr.log').open('w') as stderr:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],cwd=root,env=env,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps(dict(reloaded=True,pid=child.pid,motion_started=False)))
