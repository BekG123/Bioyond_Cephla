"""Reload an idle, robot-disconnected console after the chat reply fix."""
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import psutil

root=Path(__file__).resolve().parents[1]
def read(path):
    with urlopen('http://127.0.0.1:5002/'+path,timeout=10) as response:
        return json.load(response)

def post(path,body=None):
    request=Request('http://127.0.0.1:5002/'+path,
        data=json.dumps(body or {}).encode(),headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=10) as response:result=json.load(response)
    if result.get('ok') is not True:raise RuntimeError(path+' failed: '+str(result))
    return result

state=read('state');chat=read('researcher/api/lacry/state')
connected=state['robot']['connected']
idle_home='--idle-home' in sys.argv
if ((connected and not idle_home) or state['sequence']['active'] or chat.get('busy')
        or chat.get('running',{}).get('active') or chat.get('pending')
        or chat.get('review') or (chat.get('question') and not idle_home)):
    raise RuntimeError('Reload requires disconnected arm and idle chat with no pending decisions.')
if connected:
    # Explicit reload at the observed empty-jaw HOME clearance. Never stop,
    # restart, enable or clear the controller; only replace its console socket.
    robot=state['robot']
    target=dict(X=312.5,Y=-66.3,Z=105.72,Rz=89.84)
    if (not robot.get('ok') or robot.get('errors') or
            abs(robot.get('external_axes',{}).get('E1',0)-28)>.15 or
            any(abs(robot.get('pose_mm',{}).get(k,1e9)-v)>.2 for k,v in target.items())):
        raise RuntimeError('Not at the checked open-jaw HOME clearance.')
    time.sleep(.5)
    again=read('state')
    if again['sequence']['active'] or any(abs(again['robot']['pose_mm'][k]-robot['pose_mm'][k])>.02 for k in target):
        raise RuntimeError('Arm is changing position; no reload.')
owners={c.pid for c in psutil.net_connections('tcp') if c.status=='LISTEN' and c.laddr.port==5002}
if len(owners)!=1:raise RuntimeError('Ambiguous console owner.')
process=psutil.Process(owners.pop())
if Path(process.cwd()).resolve()!=root or 'operator_ui/app.py' not in process.cmdline():
    raise RuntimeError('Unexpected console owner.')
environment=process.environ()
folder=root/'operator_ui/reports/deployments'/('reply_filter_'+str(time.time_ns()))
folder.mkdir(parents=True)
(folder/'before.json').write_text(json.dumps(dict(state=state,chat=chat),indent=2))
if connected:
    post('camera/release')
    post('disconnect')
process.terminate();process.wait(10)
with (folder/'stdout.log').open('w') as out,(folder/'stderr.log').open('w') as err:
    child=subprocess.Popen([str(root/'.venv-realsense/Scripts/python.exe'),'-B','-u','operator_ui/app.py'],
        cwd=root,env=environment,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
for _ in range(25):
    time.sleep(1)
    if child.poll() is not None:raise RuntimeError('Console exited; inspect '+str(folder))
    try:
        after=read('state');read('researcher/api/lacry/state')
        break
    except OSError:pass
else:raise RuntimeError('Console did not become ready; no restart retry.')
if after['robot']['connected'] or after['sequence']['active']:
    raise RuntimeError('Unexpected robot connection or activity after reload.')
if connected:
    post('connect',dict(ip=state['robot']['endpoint'].split(':')[0]))
    after=read('state');robot=after['robot']
    if (any(abs(robot['pose_mm'][k]-state['robot']['pose_mm'][k])>.05 for k in target)
            or abs(robot['external_axes']['E1']-state['robot']['external_axes']['E1'])>.05
            or robot['enabled']!=state['robot']['enabled']
            or robot['program_state']!=state['robot']['program_state']):
        raise RuntimeError('Controller state changed across reload; inspect before any movement.')
(folder/'after.json').write_text(json.dumps(after,indent=2))
print(json.dumps(dict(reloaded=True,pid=child.pid,robot_connected=after['robot']['connected'],motion_started=False,report=str(folder))))
