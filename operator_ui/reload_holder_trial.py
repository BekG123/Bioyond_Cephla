"""Reload an idle, stopped console for holder commissioning; no robot motion."""
import json
import subprocess
import sys
import time
from pathlib import Path
import psutil
from proof_lift_plate import api, near
from draggo import DragGoRPC

root = Path(__file__).resolve().parents[1]
s = api('state')
if not s['robot'].get('connected'):
    assert not s['sequence']['active']
    assert api('connect', {'ip': '192.168.201.220'})['ok']
    s = api('state')
r = s['robot']
assert r['ok'] and not r['errors'] and not s['sequence']['active']
returning = sys.argv[1:] == ['--return-original']
fast = sys.argv[1:] == ['--fast137']
origin_fix = sys.argv[1:] == ['--fast-origin-fix']
quarter = sys.argv[1:] == ['--quarter-turn'] or returning or origin_fix
assert not sys.argv[1:] or quarter or fast
if quarter:
    assert r['program_state']['state'] == 'running' and r['enabled'] and r['control_mode']['mode'] == 'auto'
else:
    assert r['program_state']['state'] == 'stopped'
    if not fast:
        assert not r['enabled']
assert api('researcher/api/status')['hand_guiding']['state'] == 'off'
assert not api('researcher/api/lacry/state')['running']['active']
n = DragGoRPC('192.168.201.220').info()
assert not any(n[k] for k in ('moving', 'error', 'emergency', 'drag'))
near(r['pose_mm'], dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88), .2)
assert abs(n['external_axes']['E1']) < .5
time.sleep(.3)
near(api('state')['robot']['pose_mm'], r['pose_mm'], .05)
listeners = [c for c in psutil.net_connections('tcp') if c.status == 'LISTEN' and c.laddr.port == 5002]
assert len({c.pid for c in listeners}) == 1
p = psutil.Process(listeners[0].pid)
assert 'operator_ui/app.py' in p.cmdline()
env = p.environ()
folder = root/'operator_ui/reports/holder_short_side'/('reload_fast_origin_fix' if origin_fix else 'reload_fast137' if fast else 'reload_return_original' if returning else 'reload_quarter_turn' if quarter else 'reload')
folder.mkdir(parents=True, exist_ok=False)
(folder/'before.json').write_text(json.dumps(s, indent=2))
assert api('camera/release', {})['ok']
assert api('disconnect', {})['ok']
p.terminate()
p.wait(10)
with (folder/'stdout.log').open('w') as out, (folder/'stderr.log').open('w') as err:
    child = subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'), '-B', '-u', 'operator_ui/app.py'], cwd=root, env=env, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps(dict(pid=child.pid, reloaded=True, motion=False)))
