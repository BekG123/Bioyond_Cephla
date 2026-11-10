"""Reload singleton while the confirmed empty arm is disabled and stationary."""
import json
import subprocess
import time
from pathlib import Path
import psutil
from proof_lift_plate import api,near
from draggo import DragGoRPC
from hamilton_short_side_trial import reference,validate_route,FOLDER

root=Path(__file__).resolve().parents[1]
p,parent=reference();s=api('state')
assert not s['sequence']['active']
if not s['robot'].get('connected'):
    assert api('connect',{'ip':'192.168.201.220'})['ok'];s=api('state')
r=s['robot'];n=DragGoRPC('192.168.201.220').info()
assert r['ok'] and not r['errors'] and not r['enabled'] and r['program_state']['state'] in ('paused','stopped')
assert not any(n[k] for k in ('moving','error','emergency','drag'))
assert abs(n['external_axes']['E1'])<.15
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
cfg=api('robot_params');env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
assert s['envelope']['enabled']
validate_route(r['pose_mm'],p['routes']['reverse']['points'],r['joints'],cfg,env,'reverse')
time.sleep(.3);near(api('state')['robot']['pose_mm'],r['pose_mm'],.05)
listeners=[c for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002]
assert len({c.pid for c in listeners})==1
process=psutil.Process(listeners[0].pid);assert 'operator_ui/app.py' in process.cmdline();env=process.environ()
folder=FOLDER/'reload_hamilton_short_side';folder.mkdir(exist_ok=False)
(folder/'before.json').write_text(json.dumps(dict(state=s,native=n),indent=2))
assert api('camera/release',{})['ok'];assert api('disconnect',{})['ok']
process.terminate();process.wait(10)
with (folder/'stdout.log').open('w') as out,(folder/'stderr.log').open('w') as err:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],cwd=root,env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps(dict(reloaded=True,pid=child.pid,motion_started=False)))
