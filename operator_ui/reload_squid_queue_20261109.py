"""Load queue 220109 host support while stopped; never start robot hardware."""
import json
import subprocess
import time
from pathlib import Path
import psutil
from proof_lift_plate import api,near

root=Path(__file__).resolve().parents[1]
state=api('state');r=state['robot']
assert r.get('connected') and r['ok'] and not r['errors']
assert not state['sequence']['active'] and r['program_state']['state']=='stopped'
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
time.sleep(.5)
second=api('state')
assert not second['sequence']['active'] and second['robot']['program_state']['state']=='stopped'
near(second['robot']['pose_mm'],r['pose_mm'],.05)
listeners=[c for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002]
assert len({c.pid for c in listeners})==1
p=psutil.Process(listeners[0].pid)
assert 'operator_ui/app.py' in p.cmdline()
env=p.environ()
folder=root/'operator_ui/reports/squid_queue_reload_20261109'
folder.mkdir(exist_ok=False)
(folder/'before.json').write_text(json.dumps(state,indent=2))
assert api('camera/release',{})['ok']
assert api('disconnect',{})['ok']
p.terminate();p.wait(10)
with (folder/'stdout.log').open('w') as stdout,(folder/'stderr.log').open('w') as stderr:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],cwd=root,env=env,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps(dict(reloaded=True,pid=child.pid,motion_started=False)))
