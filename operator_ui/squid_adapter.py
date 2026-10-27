"""Read-only local Squid connection: native TCP status + native run.json.

Only ping/status commands are exposed here. Imaging starts, stage moves and
robot moves are deliberately not part of this connection adapter.
"""
from copy import deepcopy
import json
import logging
import math
import os
from pathlib import Path
import socket
import threading
import time

from researcher_teaching import TeachingError
from squid_bridge.state_io import read_json as read_shared_json

ROOT = Path(__file__).resolve().parent
STATE_FILE = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.local/state'))/'cephla/squid/watchdog/run.json'


def squid_process(port=5050):
    import psutil
    candidates = []
    for process in psutil.process_iter(['pid', 'name']):
        if 'python' not in (process.info['name'] or '').lower():
            continue
        try:
            args = process.cmdline()
            native = any(Path(arg).name == 'main_hcs.py' for arg in args)
            addon = any(Path(arg).resolve() == ROOT/'squid_bridge/launch.py' for arg in args)
            if not (native or addon):
                continue
            cwd = Path(process.cwd())
            if not (cwd/'squid/acquisition_state.py').is_file():
                continue
            listeners = process.net_connections(kind='tcp')
            if not any(c.status == psutil.CONN_LISTEN and c.laddr.port == port
                       and c.laddr.ip == '127.0.0.1' for c in listeners):
                continue
            override = process.environ().get('SQUID_WATCHDOG_STATE_DIR')
            stage_mock = '--simulation' in args
            camera_mock = stage_mock or (addon and any(a in args for a in ('--simulate-camera','--stage-only')))
            controller_serial = args[args.index('--controller-serial')+1] if '--controller-serial' in args else None
            candidates.append(dict(pid=process.pid, created_at=process.create_time(),
                                   simulation=camera_mock, stage_simulated=stage_mock,
                                   camera_simulated=camera_mock, controller_serial=controller_serial, software=str(cwd),
                                   state_file=str(Path(override)/'run.json' if override else STATE_FILE)))
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    if len(candidates) != 1:
        raise TeachingError('Squid status connection unavailable. In Squid, enable Settings → Enable MCP Control Server. Then select Connect to Squid. Python Exec is not needed.')
    return candidates[0]


def native_command(command, params=None, port=5050, timeout=30):
    """Private transport; workflows expose only explicitly allowed commands."""
    with socket.create_connection(('127.0.0.1', port), timeout=2) as sock:
        sock.settimeout(timeout)
        sock.sendall((json.dumps(dict(command=command, params=params or {}))+'\n').encode())
        data = b''
        while b'\n' not in data:
            chunk = sock.recv(8192)
            if not chunk or len(data)+len(chunk) > 1_000_000:
                raise ValueError('Incomplete Squid response.')
            data += chunk
    result = json.loads(data.split(b'\n', 1)[0])
    if result.get('success') is not True or not isinstance(result.get('result'), dict):
        raise ValueError(str(result.get('error') or 'Squid did not acknowledge the request.'))
    return result['result']


def read_command(command, port=5050):
    if command not in ('ping', 'get_acquisition_status'):
        raise ValueError('This adapter only reads Squid status.')
    return native_command(command, port=port, timeout=2)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class SquidAdapter:
    def __init__(self, *, port=5050, identify=None, request=None, clock=time.time,
                 log_path=None, background=True):
        self.port, self.clock = port, clock
        self.identify = identify or (lambda: squid_process(port))
        self.request = request or (lambda command: read_command(command, port))
        self.log_path = Path(log_path or ROOT/'logs/squid/events.jsonl')
        self.completion_path=self.log_path.with_suffix('.completion.json')
        self.background = background
        self.lock = threading.RLock()
        self.poll_lock = threading.Lock()
        self.owner = None
        self.connected_at = None
        self.enabled = False
        self.thread = None
        self.on_event = None
        self.seen = set()
        self.uncertain = set()
        self.last_event = None
        self.gap = False
        self.snapshot = dict(available=True, connected=False, status='disconnected',
                             message='Connect to Squid to follow imaging progress.',
                             job=None, completion_confirmed=False, simulation=None)

    def status(self):
        with self.lock:
            result = deepcopy(self.snapshot)
        if result.get('connected') and self.clock()-result.get('checked_at', 0) > 10:
            result.update(connected=False, status='unknown', completion_confirmed=False,
                          real_imaging_complete=False,
                          message='Squid status is stale. Imaging completion is not confirmed.')
        return result

    def connect(self):
        with self.poll_lock:
            try:
                owner = self.identify()
                if self.request('ping').get('status') != 'ok':
                    raise ValueError('The status server did not acknowledge the connection.')
            except TeachingError:
                raise
            except (OSError, ValueError) as error:
                raise TeachingError('Could not connect to Squid. Check its local control server and try Connect again. '+str(error)) from None
            with self.lock:
                if self.enabled and self.owner == owner and self.snapshot.get('connected') and not self.gap:
                    return self.status()
                self.owner = owner
                self.connected_at = self.clock()
                self.enabled = True
                self.seen = set()
                self.uncertain = set()
                self.last_event = None
                self.gap = False
        self.poll()
        if self.background and not (self.thread and self.thread.is_alive()):
            self.thread = threading.Thread(target=self._monitor, daemon=True, name='squid-status')
            self.thread.start()
        state = self.status()
        if not state['connected']:
            raise TeachingError(state['message'])
        return state

    def _monitor(self):
        while self.enabled:
            time.sleep(1)
            self.poll()

    def _job(self, api, now):
        path = Path(self.owner['state_file'])
        try:
            run = read_shared_json(path)
        except FileNotFoundError:
            return None, ('running' if api['in_progress'] else 'idle'), False
        if (run.get('schema_version') != 1 or not isinstance(run.get('run_id'), str)
                or not run['run_id'] or not finite(run.get('started_at'))):
            raise ValueError('Squid acquisition record is invalid.')
        # A record from an earlier process is historical, not a current plate.
        if run.get('pid') != self.owner['pid'] or run['started_at'] < self.owner['created_at']:
            return None, ('running' if api['in_progress'] else 'idle'), False
        job = {key: run.get(key) for key in
               ('run_id', 'experiment_id', 'started_at', 'ended_at', 'progress', 'expected',
                'stats', 'reason', 'output_path', 'heartbeat_at')}
        ident = job['run_id']
        if self.gap:
            return job, 'unknown', False
        if api.get('experiment_id') != job['experiment_id']:
            return job, 'unknown', False
        # Observing an already-running acquisition is allowed. An ended record
        # that predates Connect is never a fresh completion notification.
        if run.get('status') == 'running':
            if api['in_progress']:
                self.seen.add(ident)
            if not finite(job['heartbeat_at']) or now-job['heartbeat_at'] > 60:
                self.uncertain.add(ident)
                return job, 'unknown', False
            return job, ('running' if api['in_progress'] else 'unknown'), False
        if run.get('status') != 'ended' or not finite(job['ended_at']):
            return job, 'unknown', False
        eligible = ident in self.seen or run['started_at'] >= self.connected_at or self._recorded_completion(job)
        if not eligible:
            return job, 'historical', False
        if ident in self.uncertain:
            return job, 'unknown', False
        cleanup=api.get('cleanup') or {}
        if cleanup.get('version')==1:
            if cleanup.get('experiment_id')!=job['experiment_id']:
                return job,'unknown',False
            if cleanup.get('status')=='failed':return job,'failed',False
            if cleanup.get('status') in ('pending','running'):return job,'finishing',False
            if cleanup.get('status')!='completed':return job,'unknown',False
        elif self.owner.get('stage_simulated') is False:
            return job,'cleanup_unverified',False
        if api['in_progress']:
            return job, 'finishing', False
        reason = run.get('reason')
        if reason == 'user_abort':
            return job, 'aborted', False
        if reason in ('error', 'completed_with_errors', 'start_failed'):
            return job, 'failed', False
        stats = run.get('stats') or {}
        if (reason == 'completed' and finite(stats.get('total_images'))
                and stats['total_images'] > 0 and stats.get('errors_encountered') == 0):
            return job, 'completed', True
        return job, 'unknown', False

    def _recorded_completion(self,job):
        """Revalidate a host-observed completion after a console-only restart.

        Native session, current acquisition ID and terminal result must still
        agree. A disconnect/uncertain observation invalidates this receipt.
        This is completion evidence, never authorization to retrieve a plate.
        """
        try:receipt=json.loads(self.completion_path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):return False
        previous=receipt.get('job') or {}
        return (receipt.get('status')=='completed' and receipt.get('completion_confirmed') is True
            and receipt.get('session')==dict(pid=self.owner['pid'],created_at=self.owner['created_at'])
            and finite(receipt.get('checked_at')) and finite(job.get('ended_at'))
            and receipt['checked_at']>=job['ended_at']
            and all(previous.get(k)==job.get(k) for k in
                    ('run_id','experiment_id','started_at','ended_at','reason','stats')))

    def poll(self):
        if not self.enabled:
            return self.status()
        with self.poll_lock:
            now = self.clock()
            try:
                owner = self.identify()
                if owner != self.owner:
                    raise ValueError('Squid restarted. Connect again to follow the new session.')
                api = self.request('get_acquisition_status')
                if type(api.get('in_progress')) is not bool:
                    raise ValueError('Squid returned an invalid acquisition state.')
                job, status, complete = self._job(api, now)
                mock = 'Mock ' if owner['simulation'] else ''
                descriptions = dict(idle='ready; no imaging run in progress.',
                    running='imaging in progress.', finishing='finishing image processing and cleanup.',
                    completed='imaging complete.', aborted='imaging was cancelled.',
                    failed='imaging failed or completed with errors.',
                    unknown='imaging status is uncertain; completion is not confirmed.',
                    cleanup_unverified='images finished; stage cleanup is unverified. Load the updated Squid add-on before automatic retrieval.',
                    historical='connected; the previous imaging record is historical.')
                snapshot = dict(available=True, connected=True, status=status,
                    message=f'Squid {mock.lower()}{descriptions[status]}',
                    simulation=owner['simulation'], job=job, completion_confirmed=complete,
                    real_imaging_complete=complete and not owner['simulation'],
                    checked_at=now, session=dict(pid=owner['pid'], created_at=owner['created_at']),
                    monitoring_only=True, retrieval_authorized=False)
                if api.get('cleanup'):
                    snapshot['cleanup']=deepcopy(api['cleanup'])
                if 'stage_simulated' in owner:
                    snapshot.update(stage_simulated=owner['stage_simulated'],
                                    camera_simulated=owner['camera_simulated'],
                                    controller_serial=owner.get('controller_serial'))
                    if owner['camera_simulated'] and not owner['stage_simulated']:
                        snapshot['message'] = 'Squid real-stage test with simulated camera: '+descriptions[status]
                if status=='failed' and api.get('cleanup',{}).get('status')=='failed':
                    snapshot['message']='Squid stage cleanup failed after imaging: '+str(api['cleanup'].get('error','unknown error'))+'. No retrieval is authorized.'
            except Exception as error:
                self.gap = True
                old_job = self.snapshot.get('job')
                if old_job:
                    self.uncertain.add(old_job['run_id'])
                snapshot = dict(available=True, connected=False, status='disconnected',
                    message='Squid disconnected: '+str(error), job=deepcopy(old_job),
                    simulation=self.owner.get('simulation') if self.owner else None,
                    completion_confirmed=False, real_imaging_complete=False,
                    checked_at=now, monitoring_only=True, retrieval_authorized=False)
            with self.lock:
                self.snapshot = snapshot
            job = snapshot.get('job') or {}
            key = (snapshot['connected'], job.get('run_id'), snapshot['status'])
            changed = key != self.last_event
            self.last_event = key
        if changed:
            event = dict(at=now, **deepcopy(snapshot))
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                temporary=self.completion_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(snapshot if snapshot.get('completion_confirmed') and snapshot.get('connected') else {},allow_nan=False),encoding='utf-8')
                temporary.replace(self.completion_path)
                with self.log_path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(event, allow_nan=False)+'\n')
                if self.on_event:
                    self.on_event(event)
            except Exception:
                logging.exception('Squid status notification could not be recorded.')
        return self.status()

    def job_status(self, job_id=None):
        state = self.poll()
        job=state.get('job') or {}
        if job_id and job_id not in (job.get('run_id'),job.get('experiment_id')):
            raise TeachingError('That identifier does not match the observed Squid job. Read get_squid_status without a job_id to inspect the current job; this does not mean no acquisition exists.')
        return state
