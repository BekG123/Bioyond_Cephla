"""Record accepted closed-claw batch and reload idle host only; no robot startup."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import psutil
from proof_lift_plate import api,near

root=Path(__file__).resolve().parents[1]
batch=root/'operator_ui/reports/squid_48well_approach/queued_hamilton_squid_five_20261110'
data=json.loads((batch/'run.json').read_bytes())
assert data['completed_cycles']==5 and data['status']=='completed_pending_operator_assessment'
accept=batch/'operator_acceptance.json'
if not accept.exists():
    evidence={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in batch.rglob('*.json')}
    with accept.open('x',encoding='utf-8') as f:json.dump(dict(at=time.time(),operator_statement='Yes, this was succesful.',
        completed_cycles=5,scope='Closed-gripper Hamilton-Home-Squid-Home-Hamilton; plate remained secure',evidence_sha256=evidence,telemetry_modified=False),f,indent=2)
    obs=root/'operator_ui/reports/trajectory_smoothing/Observations.md'
    with obs.open('a',encoding='utf-8') as f:f.write('\n## Five queued closed-gripper round trips accepted - November 9, 2026\n\nFive Hamilton/Home/Squid/Home/Hamilton cycles completed in 196.66 s (about 39 s each), no controller errors, grip about 3.90 mm. Operator confirmed success. Travel137, Squid descent/lift5, one Lua queue per Squid direction. No releases tested in this batch. Evidence: `../squid_48well_approach/queued_hamilton_squid_five_20261110/operator_acceptance.json`.\n')
s=api('state')
if not s['robot'].get('connected'):
    assert not s['sequence']['active'];assert api('connect',{'ip':'192.168.201.220'})['ok'];s=api('state')
r=s['robot']
assert r['ok'] and not r['errors'] and not s['sequence']['active']
assert r['enabled'] and r['control_mode']['mode']=='auto' and r['program_state']['state']=='running'
near(r['pose_mm'],dict(X=186.42,Y=-366.27,Z=45.2,Rz=-1.1),.05)
assert abs(r['external_axes']['E1']-3.9)<.15
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
time.sleep(.5);near(api('state')['robot']['pose_mm'],r['pose_mm'],.05)
listeners=[c for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002]
assert len({c.pid for c in listeners})==1
p=psutil.Process(listeners[0].pid);assert 'operator_ui/app.py' in p.cmdline();env=p.environ()
folder=root/'operator_ui/reports/hamilton_handling_reload_20261110';folder.mkdir(exist_ok=False)
(folder/'before.json').write_text(json.dumps(s,indent=2))
assert api('camera/release',{})['ok'];assert api('disconnect',{})['ok']
p.terminate();p.wait(10)
with (folder/'stdout.log').open('w') as stdout,(folder/'stderr.log').open('w') as stderr:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],cwd=root,env=env,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps(dict(reloaded=True,pid=child.pid,robot_startup=False,motion_started=False)))
