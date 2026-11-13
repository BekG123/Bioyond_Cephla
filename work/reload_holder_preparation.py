"""Load the holder-planning fix at the operator-confirmed empty HOME pose.

Only camera/socket release, console replacement, and reconnect. No controller
startup, enable, holder, gripper, reset, imaging or motion commands.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]


def request(path,body=None):
    req=Request('http://127.0.0.1:5002/'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=15) as response:return json.load(response)


def main():
    before=request('state');chat=request('researcher/api/lacry/state');robot=before['robot']
    target=dict(X=312.5,Y=-66.3,Z=105.72,Rz=89.84)
    if (before['sequence']['active'] or chat.get('busy') or chat.get('pending') or chat.get('review')
            or chat.get('question') or chat.get('running',{}).get('active')
            or not robot.get('ok') or not robot.get('connected') or robot.get('errors')
            or robot['program_state']['state']!='running' or not robot['enabled']
            or robot['control_mode']['mode']!='auto'
            or abs(robot['external_axes']['E1']-.019)>.05
            or any(abs(robot['pose_mm'][k]-v)>.05 for k,v in target.items())):
        raise RuntimeError('Setup changed from confirmed empty HOME; no reload.')
    time.sleep(.5);again=request('state')
    if again['sequence']['active'] or any(abs(again['robot']['pose_mm'][k]-robot['pose_mm'][k])>.02 for k in target):
        raise RuntimeError('Arm changed; no reload.')
    report=ROOT/'operator_ui/reports/deployments'/('holder_preparation_'+str(time.time_ns()))
    report.mkdir(parents=True);(report/'before.json').write_text(json.dumps(before,indent=2))
    for endpoint in ('camera/release','disconnect'):
        result=request(endpoint,{})
        if result.get('ok') is not True:raise RuntimeError(str(result))
    subprocess.run([sys.executable,'-B','work/reload_lacry_reply_fix.py'],cwd=ROOT,check=True)
    result=request('connect',dict(ip=robot['endpoint'].split(':')[0]))
    if result.get('ok') is not True:raise RuntimeError(str(result))
    after=request('state');actual=after['robot']
    if (after['sequence']['active'] or actual.get('errors')
            or any(abs(actual['pose_mm'][k]-robot['pose_mm'][k])>.05 for k in target)
            or abs(actual['external_axes']['E1']-robot['external_axes']['E1'])>.05
            or actual['program_state']!=robot['program_state'] or actual['enabled']!=robot['enabled']):
        raise RuntimeError('Controller state changed; inspect before motion.')
    (report/'after.json').write_text(json.dumps(after,indent=2))
    print(json.dumps(dict(reloaded=True,motion_sent=False,report=str(report))))


if __name__=='__main__':main()
