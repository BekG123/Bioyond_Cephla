"""Validate recovery from fresh feedback; optionally reload idle host, no motion."""
import sys,json,subprocess,time
from pathlib import Path
import psutil
from proof_lift_plate import api,near
from hamilton_stopped_return import plan
root=Path(__file__).resolve().parents[1]
s=api('state')
if not s['robot'].get('connected'):
    assert not s['sequence']['active'];assert api('connect',dict(ip='192.168.201.220'))['ok'];s=api('state')
r=s['robot']
assert r['ok'] and not r['errors'] and r['enabled'] and r['control_mode']['mode']=='auto' and r['program_state']['state']=='running' and not s['sequence']['active']
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
candidate=plan(r,api('robot_params'),env)
print(json.dumps(dict(vertices=candidate['vertices'],speeds=[g['speed'] for g in candidate['groups']],dense_samples=candidate['dense_samples'],e1=candidate['e1'])),flush=True)
if sys.argv[1:]!=['--reload']:sys.exit(0)
time.sleep(.3);near(api('state')['robot']['pose_mm'],r['pose_mm'],.02)
folder=root/'operator_ui/reports/integrated_dry_mock_site6_20261110/recovery_reload_retry01';folder.mkdir(parents=True,exist_ok=False)
(folder/'review.json').write_text(json.dumps(candidate,indent=2))
listeners=[c for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002]
assert len({c.pid for c in listeners})==1
p=psutil.Process(listeners[0].pid);assert 'operator_ui/app.py' in p.cmdline();env=p.environ()
assert api('camera/release',{})['ok'];assert api('disconnect',{})['ok'];p.terminate();p.wait(10)
with (folder/'stdout.log').open('w') as out,(folder/'stderr.log').open('w') as err:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],cwd=root,env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps(dict(pid=child.pid,reloaded=True,robot_startup=False,motion=False)))
