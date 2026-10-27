"""Operator-authorized simulation trial. Never connects to the robot."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import psutil

from squid_adapter import squid_process, STATE_FILE

ROOT = Path(__file__).resolve().parent


def command(name, params=None, timeout=10):
    with socket.create_connection(('127.0.0.1',5050), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((json.dumps(dict(command=name,params=params or {}))+'\n').encode())
        data=b''
        while b'\n' not in data:
            part=sock.recv(8192)
            if not part or len(data)+len(part)>1000000:raise RuntimeError('Incomplete response')
            data+=part
    result=json.loads(data.split(b'\n',1)[0])
    if result.get('success') is not True:raise RuntimeError(result.get('error','Squid refused'))
    return result['result']


def web(path, body=None):
    request=urllib.request.Request('http://127.0.0.1:5002'+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)


def settings_check(process):
    # Reads configuration only; never instantiates a microscope.
    code=("import control._def as c,json; print('LACRY_CHECK:'+json.dumps({"
          "'slack':bool(c.SlackNotifications.ENABLED),"
          "'simulated_disk_io':bool(c.SIMULATED_DISK_IO_ENABLED)}))")
    result=subprocess.run([process.exe(),'-c',code],cwd=process.cwd(),
                          capture_output=True,text=True,timeout=30)
    lines=[x.split('LACRY_CHECK:',1)[1] for x in result.stdout.splitlines() if x.startswith('LACRY_CHECK:')]
    if result.returncode or len(lines)!=1:raise RuntimeError('Could not verify simulator notification configuration.')
    flags=json.loads(lines[0])
    if flags['slack']:raise RuntimeError('Mock test blocked: external notifications are enabled.')
    if flags['simulated_disk_io']:raise RuntimeError('Mock test needs actual image files, not simulated disk writes.')


def enable_server(pid):
    process=psutil.Process(pid)
    args=process.cmdline()
    if '--simulation' not in args or not any(Path(a).name=='main_hcs.py' for a in args):
        raise RuntimeError('Only the explicitly identified Squid simulator may be restarted.')
    software=Path(process.cwd())
    if not (software/'squid/acquisition_state.py').is_file():raise RuntimeError('Wrong Squid checkout.')
    settings_check(process)
    state_path=Path(process.environ().get('SQUID_WATCHDOG_STATE_DIR',str(STATE_FILE.parent)))/'run.json'
    if state_path.exists():
        record=json.loads(state_path.read_text())
        if record.get('pid')==pid and record.get('status')=='running':
            raise RuntimeError('The simulator is acquiring; leave it untouched.')
    try:
        if command('ping',timeout=2).get('status')=='ok':
            print('Status server already running.');return
    except (OSError,RuntimeError):pass
    executable=process.exe()
    output=ROOT/'reports/squid_connection'
    output.mkdir(parents=True,exist_ok=True)
    # Open logs before stopping the simulator so permission failures cannot
    # leave it stopped. No controller reset, robot enable or robot connection.
    with (output/'simulator.stdout.log').open('a') as stdout, (output/'simulator.stderr.log').open('a') as stderr:
        children=process.children(recursive=True)
        for child in children:
            try:child.terminate()
            except psutil.NoSuchProcess:pass
        process.terminate()
        psutil.wait_procs([process]+children,timeout=8)
        if process.is_running():raise RuntimeError('Simulator did not stop; no second instance launched.')
        launched=subprocess.Popen([executable,'-B','main_hcs.py','--simulation','--start-server'],
            cwd=software,stdout=stdout,stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    print('Starting Squid simulator with local status server, PID',launched.pid,flush=True)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if launched.poll() is not None:raise RuntimeError('Simulator exited; inspect its saved stderr log.')
        try:
            owner=squid_process()
            if owner['pid']==launched.pid and command('ping',timeout=2).get('status')=='ok':
                print(json.dumps(dict(ready=True,pid=launched.pid,simulation=owner['simulation'])));return
        except Exception as error:
            last=str(error)
        time.sleep(1)
    raise RuntimeError('Simulator startup not confirmed: '+last)


def mock_trial():
    owner=squid_process()
    if not owner['simulation']:raise RuntimeError('Mock trial requires Squid --simulation.')
    settings_check(psutil.Process(owner['pid']))
    if command('get_acquisition_status')['in_progress']:raise RuntimeError('An acquisition is already running.')
    link=web('/researcher/api/lacry/link/squid',{})
    if not link.get('ok') or not link['instrument']['simulation']:raise RuntimeError('Lacry simulation link is not ready.')
    channels=command('get_channels')['channels']
    channel=next((c for c in channels if 'BF' in c or 'Brightfield' in c),None)
    if not channel:raise RuntimeError('No brightfield channel found for this mock.')
    name='Lacry_mock_'+time.strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:6]
    folder=ROOT/'reports/squid_connection'/name
    folder.mkdir(parents=True)
    record=dict(mock=True,simulation=True,owner=owner,request=dict(wells='A1',channels=[channel],
        nx=1,ny=1,experiment_id=name,base_path=str(folder/'images'),wellplate_format='96 well plate'),
        snapshots=[],status='prepared',hardware_commands=0)
    path=folder/'trial.json'
    path.write_text(json.dumps(record,indent=2))
    if squid_process()!=owner:raise RuntimeError('Squid process changed before mock start.')
    record['response']=command('run_acquisition',record['request'],timeout=30)
    record['status']='started'
    path.write_text(json.dumps(record,indent=2))
    print('Mock imaging started:',record['response'].get('experiment_id'),flush=True)
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        state=web('/researcher/api/lacry/state')
        observed=state['links']['squid']
        record['snapshots'].append(observed)
        path.write_text(json.dumps(record,indent=2))
        job=observed.get('job') or {}
        if job.get('experiment_id')==record['response']['experiment_id']:
            if observed['status']=='completed' and observed['completion_confirmed']:
                if observed['real_imaging_complete']:raise RuntimeError('Mock was incorrectly classified as real.')
                record.update(status='passed',job_id=job['run_id'],final=observed,
                    transcript_tail=state['transcript'][-4:],
                    image_files=[str(p) for p in folder.rglob('*.tif*')])
                path.write_text(json.dumps(record,indent=2))
                print(json.dumps(dict(status='passed',job_id=job['run_id'],images=len(record['image_files']),report=str(path))))
                return
            if observed['status'] in ('failed','aborted','unknown','disconnected'):
                record['status']='failed';path.write_text(json.dumps(record,indent=2))
                raise RuntimeError(observed['message'])
        time.sleep(1)
    record['status']='timeout';path.write_text(json.dumps(record,indent=2))
    raise RuntimeError('Mock completion not confirmed; no automatic retry.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--enable-simulation-server',type=int,metavar='PID')
    group.add_argument('--mock-acquisition',action='store_true')
    arguments=parser.parse_args()
    if arguments.enable_simulation_server:enable_server(arguments.enable_simulation_server)
    else:mock_trial()
