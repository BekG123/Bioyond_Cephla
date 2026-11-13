"""Reload the stopped console with restored E2 rule, preserving its environment."""
import json
import subprocess
import time
from pathlib import Path
import psutil
from proof_lift_plate import api

root = Path(__file__).resolve().parents[1]
state = api('state')
robot = state['robot']
assert not state['sequence']['active'] and robot['ok'] and not robot['errors']
assert robot['program_state']['state'] == 'stopped'
assert api('researcher/api/status')['hand_guiding']['state'] == 'off'
assert not api('researcher/api/lacry/state')['running']['active']
time.sleep(.5)
second = api('state')
assert not second['sequence']['active']
assert all(abs(second['robot']['pose_mm'][k]-robot['pose_mm'][k]) < .05 for k in ('X','Y','Z','Rz'))
listeners = [c for c in psutil.net_connections('tcp') if c.status == 'LISTEN' and c.laddr.port == 5002]
assert len({c.pid for c in listeners}) == 1
process = psutil.Process(listeners[0].pid)
assert 'operator_ui/app.py' in process.cmdline()
env = process.environ()
folder = root / 'operator_ui/reports/e2_previous_restored_20261109'
folder.mkdir(exist_ok=False)
(folder/'before_reload.json').write_text(json.dumps(state, indent=2))
assert api('camera/release', {})['ok']
assert api('disconnect', {})['ok']
process.terminate()
process.wait(10)
with (folder/'console.stdout.log').open('w') as stdout, (folder/'console.stderr.log').open('w') as stderr:
    child = subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'), '-B', '-u', 'operator_ui/app.py'], cwd=root, env=env, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps({'pid':child.pid,'reloaded':True,'motion_started':False}))
