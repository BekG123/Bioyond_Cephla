"""Load a new pinned route while the empty arm is disabled and stationary."""
import json
import sys
import subprocess
import time
from pathlib import Path
import psutil
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_alignment_trial import reference,reference_for_candidate,FOLDER

root=Path(__file__).resolve().parents[1]
smooth='--smooth' in sys.argv
recovery='--recovery-repeat01' in sys.argv
home_fix='--home-restore-fix' in sys.argv
corrected='--corrected02' in sys.argv
plan,taught=reference_for_candidate('corrected02') if corrected else reference()
s=api('state')
assert not s['sequence']['active']
if not s['robot'].get('connected'):
    assert api('connect',{'ip':'192.168.201.220'})['ok'];s=api('state')
r=s['robot']
assert r['ok'] and not r['errors']
if smooth or home_fix:
    assert r['enabled'] and r['control_mode']['mode']=='auto' and r['program_state']['state']=='running'
else:
    assert not r['enabled'] and r['program_state']['state'] in ('paused','stopped')
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
n=DragGoRPC('192.168.201.220').info()
assert not any(n[k] for k in ('moving','error','emergency','drag'))
assert abs(n['external_axes']['E1']-(28 if smooth else 0))<.15 and abs(n['external_axes']['E2']-taught['e2_degrees'])<(.5 if recovery or home_fix else .1)
near(r['pose_mm'],plan['home'] if home_fix else dict(X=304.273,Y=-63.19,Z=184.038,Rz=44.305) if recovery else taught['target'],.1)
time.sleep(.3);near(api('state')['robot']['pose_mm'],r['pose_mm'],.05)
listeners=[c for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002]
assert len({c.pid for c in listeners})==1
p=psutil.Process(listeners[0].pid);assert 'operator_ui/app.py' in p.cmdline();env=p.environ()
folder=FOLDER/('reload_corrected02' if corrected else 'reload_home_restore_fix' if home_fix else 'reload_recovery_repeat01' if recovery else 'reload_smooth' if smooth else 'reload');folder.mkdir(exist_ok=False)
(folder/'before.json').write_text(json.dumps(s,indent=2))
assert api('camera/release',{})['ok'];assert api('disconnect',{})['ok']
p.terminate();p.wait(10)
with (folder/'stdout.log').open('w') as out,(folder/'stderr.log').open('w') as err:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],cwd=root,env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps(dict(reloaded=True,pid=child.pid,motion_started=False)))
