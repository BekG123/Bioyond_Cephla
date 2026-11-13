"""Reload only an idle console; never starts or enables the robot program."""
import json
from pathlib import Path
import subprocess
import sys
import time
import psutil
from urllib.error import HTTPError

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'operator_ui'))
from proof_lift_plate import api
from draggo import DragGoRPC

def native():
    n=DragGoRPC('192.168.201.220').info()
    if any(n.get(k,True) for k in ('moving','error','emergency','drag')):
        raise RuntimeError('Console reload requires stationary fault-free arm with hand-guiding off.')
    return n

s=api('state')
supported_slot=3 if '--supported-slot3' in sys.argv else 2 if '--supported-slot2' in sys.argv else None
if supported_slot and not s['robot'].get('connected'):
    if s['sequence']['active']:raise RuntimeError('Active sequence prevents supported slot2 reload.')
    if not api('connect',{'ip':'192.168.201.220'}).get('ok'):raise RuntimeError('Connection failed.')
    s=api('state')
try:
    l=api('researcher/api/lacry/state')
except HTTPError as error:
    if error.code != 503 or s['robot'].get('connected') or s['sequence']['active']:
        raise
    # This fresh host has no SDK connection and cannot be running arm work.
    # Repair its inspected readiness-report exception without robot startup.
    l={}
if s['sequence']['active'] or l.get('running',{}).get('active'):
    raise RuntimeError('A live operation owns the console.')
before=native()
# A disconnected host has no robot connection to interrupt. Reloading it does
# not start the controller program; preserve the current jaw/enable state.
disconnected_host = not s['robot'].get('connected')
stopped_program = s['robot'].get('program_state',{}).get('state') == 'stopped'
supported_slot2 = supported_slot is not None
if supported_slot2:
    # Operator confirmed plate support and clear jaws at the completed taught
    # slot2 endpoint. Flask-only reload must not stop/restart Lua or move axes.
    from hotel_slot2_trial import geometry
    from scope_step_trial import near
    from gripper_closure import grip_feedback_matches
    near(s['robot']['pose_mm'],geometry(supported_slot)['endpoint'],.05)
    if (not grip_feedback_matches(before['external_axes']['E1'],3.9)
            or s['robot'].get('program_state',{}).get('state')!='running'
            or before.get('manual') or not before.get('enabled')):
        raise RuntimeError('Supported slot2 reload does not match the stopped-at-endpoint running Auto state.')
# With Lua already stopped and all jobs inactive, restarting only Flask cannot
# resume motion or reset the gripper. Preserve the stopped payload state.
if before['external_axes']['E1'] < 27.8 and not disconnected_host and not stopped_program and not supported_slot2:
    raise RuntimeError('Expected the open empty-jaw state from the completed HOME trial.')
listeners={c.pid for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002}
if len(listeners)!=1: raise RuntimeError('Ambiguous console process.')
process=psutil.Process(listeners.pop())
if 'operator_ui/app.py' not in process.cmdline() or Path(process.cwd()).resolve()!=root:
    raise RuntimeError('Unexpected console owner.')
environment=process.environ()
folder=root/'operator_ui/reports/pickup_holder'/('reload_'+str(time.time_ns()))
folder.mkdir(parents=True,exist_ok=False)
(folder/'before.json').write_text(json.dumps(dict(state=s,native=before),indent=2))
if not api('camera/release',{}).get('ok'): raise RuntimeError('Camera release failed.')
if s['robot'].get('connected') and not api('disconnect',{}).get('ok'):
    raise RuntimeError('Robot disconnect failed.')
native()
process.terminate(); process.wait(10)
with (folder/'stdout.log').open('w') as out,(folder/'stderr.log').open('w') as err:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],
        cwd=root,env=environment,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
for _ in range(30):
    time.sleep(1)
    if child.poll() is not None: raise RuntimeError('Console exited; inspect '+str(folder/'stderr.log'))
    try:
        after=api('state')
        break
    except OSError: pass
else: raise RuntimeError('Console readiness timed out; no motion or automatic retry.')
end=native()
if disconnected_host and (after['robot'].get('connected') or end.get('enabled') != before.get('enabled')):
    raise RuntimeError('Unexpected connection or enable-state change during disconnected console reload.')
if any(abs(end['external_axes'][k]-before['external_axes'][k])>.1 for k in ('E1','E2')):
    raise RuntimeError('Unexpected external-axis change during reload; inspect before motion.')
(folder/'after.json').write_text(json.dumps(dict(state=after,native=end,pid=child.pid,motion_started=False),indent=2))
print(json.dumps(dict(reloaded=True,pid=child.pid,motion_started=False,report=str(folder))))
