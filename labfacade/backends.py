"""Real backends. Status and reads, plus two motions:

    squid       return_to_loading    (run once on the hardware, 2026-11-11)
    bioyond_s4  run_plate_workflow   (launches the existing CLI; see its class)

Every other motion or state-change operation is unwired: bound() is False, so
the facade refuses with 'not_bound'. Wiring one means adding a binding that
calls the existing reviewed path, then a supervised check on the hardware.

The Hamilton backend has not been run against the real machine. One Bioyond
plate workflow completed through this layer on 2026-11-11. New dataset hooks
are offline-tested only; see DATASET.md for verification scope.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, Request, build_opener
from .dataset import ConsoleFrame, DatasetSources, collect_receipts, squid_sources

REPO = Path(__file__).resolve().parents[1]


class ReadOnlyBackend:
    READS = ()

    def bound(self, name):
        return name in self.READS

    def sensors(self):
        return {}

    def _journal(self, kind, data):
        journal = getattr(self, 'dataset_journal', None)
        if journal is not None:
            journal(kind, data)

    def check(self, text):
        return None

    def abort(self):
        raise NotImplementedError('No abort is wired for this machine in this build.')


class SquidBackend(ReadOnlyBackend):
    """Squid's local control server. python_exec is not reachable from here.

    One motion is wired: return_to_loading. It sends Squid's own
    return_to_recorded_dropoff with the hash of the reviewed on-disk reference,
    never coordinates. The guards mirror operator_ui/squid_stage.py.
    """
    READS = ('ping', 'get_acquisition_status', 'get_position', 'get_channels')
    INTERNAL_READS = ('get_stage_reference',)
    MOTIONS = {'return_to_loading': 'return_to_recorded_dropoff'}
    AXES = ('x_mm', 'y_mm', 'z_mm')
    TOLERANCE_MM = .02
    SETTLE_S = .2

    def __init__(self, port=5050, reference=None, sleep=time.sleep, dataset_sources=None):
        self.port, self.sleep = port, sleep
        self.reference_path = Path(reference or REPO / 'operator_ui' / 'squid_stage_reference.json')
        self.dataset_sources = dataset_sources or squid_sources(frame=ConsoleFrame())

    def bound(self, name):
        return name in self.READS or name in self.MOTIONS

    def _command(self, command, timeout, params=None):
        if command not in self.READS + self.INTERNAL_READS + tuple(self.MOTIONS.values()):
            raise PermissionError(f'{command} is not an allowed Squid command.')
        self._journal('request', dict(command=command, params=params or {}))
        with socket.create_connection(('127.0.0.1', self.port), timeout=2) as sock:
            sock.settimeout(timeout)
            sock.sendall((json.dumps(dict(command=command, params=params or {})) + '\n').encode())
            data = b''
            while b'\n' not in data:
                chunk = sock.recv(8192)
                if not chunk or len(data) + len(chunk) > 1_000_000:
                    raise ValueError('incomplete Squid response')
                data += chunk
        reply = json.loads(data.split(b'\n', 1)[0])
        self._journal('response', dict(command=command, reply=reply))
        if reply.get('success') is not True:
            raise ValueError(str(reply.get('error') or 'Squid refused the request'))
        return reply['result']

    def read_status(self):
        if self._command('ping', 2).get('status') != 'ok':
            return dict(state='unknown', detail='ping not acknowledged', source='squid tcp')
        acquisition = self._command('get_acquisition_status', 2)
        busy = acquisition.get('in_progress') is not False
        return dict(state='busy' if busy else 'idle', source='squid tcp',
                    detail='acquisition in progress' if busy else 'no acquisition running')

    # --- the reviewed loading reference -------------------------------------------------

    def _reference(self):
        """(reference, hash). The hash is computed exactly as the Squid extension computes it."""
        ref = json.loads(self.reference_path.read_text(encoding='utf-8-sig'))
        return ref, hashlib.sha256(json.dumps(ref, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def _position(self):
        value = self._command('get_position', 5)
        if any(type(value.get(k)) not in (int, float) or not math.isfinite(value[k]) for k in self.AXES):
            raise ValueError('Squid stage position is unavailable.')
        return {k: value[k] for k in self.AXES}

    def _near(self, actual, target):
        return all(abs(actual[k] - target[k]) <= self.TOLERANCE_MM for k in self.AXES)

    def _settled_at(self, target):
        first = self._position()
        self.sleep(self.SETTLE_S)
        second = self._position()
        return self._near(first, target) and self._near(second, target), second

    def preflight(self):
        """Every fact return_to_loading depends on. Reads only."""
        ref, fingerprint = self._reference()
        bridge = self._command('get_stage_reference', 5)
        acquisition = self._command('get_acquisition_status', 5)
        target = ref['dropoff']
        position = self._position()
        return dict(
            reference_confirmed=ref.get('operator_confirmed') is True,
            motion_hold=ref.get('motion_hold'),
            target_repeatable=not (ref.get('controller_serial') == '12769210'
                                   and min(target['x_mm'], target['y_mm']) < 0),
            stage_real=bridge.get('stage_simulated') is False,
            serial_matches=bridge.get('controller_serial') == ref.get('controller_serial'),
            hash_matches=bridge.get('reference_hash') == fingerprint,
            no_scan=acquisition.get('in_progress') is False
            and (acquisition.get('cleanup') or {}).get('status') != 'failed',
            position=position, target=target, at_target=self._near(position, target),
            reference_hash=fingerprint)

    def check(self, text):
        facts = None
        try:
            if text == 'Squid connected and stage not simulated':
                facts = self.preflight()
                return facts['stage_real'] and facts['reference_confirmed'] and not facts['motion_hold'] \
                    and facts['target_repeatable']
            if text == 'controller serial matches':
                return self.preflight()['serial_matches']
            if text == 'no scan running':
                return self.preflight()['no_scan']
            if text == 'reference hash matches the loaded extension':
                return self.preflight()['hash_matches']
            if text == 'position equals loading_dropoff within 0.02 mm after a 0.2 s settle':
                return self._settled_at(self._reference()[0]['dropoff'])[0]
        except Exception:
            return False            # a check that cannot be read is not passed
        return None                 # not something Squid can tell (for example where the arm is)

    def run(self, name, params, timeout_s):
        if name in self.READS:
            return self._command(name, timeout_s)
        if name != 'return_to_loading':
            raise PermissionError(f'{name} is not wired.')
        facts = self.preflight()
        failed = [k for k in ('reference_confirmed', 'target_repeatable', 'stage_real', 'serial_matches',
                              'hash_matches', 'no_scan') if facts[k] is not True]
        if failed or facts['motion_hold']:
            raise RuntimeError(f"Loading move not sent: {failed or facts['motion_hold']}")
        if facts['at_target']:
            return dict(moved=False, position=facts['position'], target=facts['target'])
        result = self._command('return_to_recorded_dropoff', max(1, timeout_s - 5),
                               dict(reference_hash=facts['reference_hash']))
        if result.get('at_dropoff') is not True:
            raise RuntimeError('Squid did not confirm its loading move. Inspect the stage; nothing was resent.')
        settled, position = self._settled_at(facts['target'])
        if not settled:
            raise RuntimeError(f"Stage is not at the loading position: {position} vs {facts['target']}.")
        return dict(moved=True, position=position, target=facts['target'], before=facts['position'])


class HamiltonBackend(ReadOnlyBackend):
    """Hamilton Prep status through the existing REST wrapper."""
    READS = ('get_status',)

    def __init__(self, dataset_sources=None, prep=None):
        self._prep = prep
        self.dataset_sources = dataset_sources or DatasetSources(frame=ConsoleFrame())

    def collect_dataset(self, run, step, operation):
        # Only this wrapper's current ticket; never scan for the newest journal,
        # mutate the ownership marker, or infer successful completion from it.
        if self._prep is None:
            return []
        ticket = getattr(self._prep, 'active', None) or {}
        request_id = ticket.get('request_id')
        if not request_id:
            return []
        from .artifacts import component
        path = self._prep.folder / (component(request_id) + '.jsonl')
        return collect_receipts(run, 'hamilton_prep', step, [path], [self._prep.folder])

    def _status(self):
        if self._prep is None:
            sys.path.insert(0, str(REPO / 'operator_ui'))
            from hamilton_prep import HamiltonPrep
            self._prep = HamiltonPrep()
        self._journal('request', dict(operation='HamiltonPrep.status', fresh=True))
        result = self._prep.status(fresh=True)
        self._journal('response', result)
        return result

    def read_status(self):
        raw = self._status()
        marker = (self._prep.folder / 'active.json').exists()
        if not raw.get('connected'):
            state, detail = 'unknown', raw.get('message', 'not connected')
        elif raw.get('pending_errors') or marker:
            state = 'error'
            detail = 'unresolved operation marker (active.json)' if marker else 'pending errors'
        else:
            state, detail = ('idle' if raw.get('state') == 'idle' else 'busy'), raw.get('message', '')
        return dict(state=state, detail=detail, source='hamilton rest')

    def run(self, name, params, timeout_s):
        raw = self._status()
        return {k: raw.get(k) for k in ('connected', 'initialized', 'global_state', 'parked',
                                         'pending_errors', 'serial', 'message')}


class BioyondConsoleBackend(ReadOnlyBackend):
    """The arm, through the operator console (:5002).

    The controller takes one TCP client, and the console holds it, so this
    reads the console's view and never opens a second connection.

    One motion is wired: run_plate_workflow. It launches the existing CLI
    (operator_ui/run_plate_workflow.py) unchanged, in the checkout the console
    runs from. The console still executes and verifies every move. The CLI's
    receipt check requires that it and the console share one folder, so
    `checkout` must be that folder; without it the operation is not bound.
    """
    READS = ('get_status',)
    WORKFLOW = 'run_plate_workflow'
    FLAGS = ('full_calibration', 'home_to_hamilton_roundtrip', 'home_to_squid_roundtrip')
    MAX_CYCLES = 5
    DONE = 'controller_completed_pending_operator_assessment'
    accepts_progress = True
    context_checks = True

    def __init__(self, base='http://127.0.0.1:5002', checkout=None, python=None, squid=None, dataset_sources=None):
        self.base = base
        self.opener = build_opener(ProxyHandler({}))
        self.checkout = Path(checkout) if checkout else None
        venv = self.checkout / '.venv-realsense' / 'Scripts' / 'python.exe' if self.checkout else None
        self.python = str(python or (venv if venv and venv.exists() else sys.executable))
        self.squid = squid                      # a SquidBackend, for the Squid readiness check
        self.process = None
        self.last_record = None                 # path of the workflow's own run.json
        self.stop_response = None
        self.dataset_sources = dataset_sources or DatasetSources(frame=ConsoleFrame(base))

    @property
    def script(self):
        return self.checkout / 'operator_ui' / 'run_plate_workflow.py' if self.checkout else None

    def bound(self, name):
        return name in self.READS or (name == self.WORKFLOW and self.script is not None and self.script.exists())

    def _api(self, path, body=None, timeout=10):
        self._journal('request', dict(path=path, body=body))
        request = Request(f'{self.base}/{path}', data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'X-Cephla-View': 'developer'})
        with self.opener.open(request, timeout=timeout) as response:
            result = json.load(response)
        self._journal('response', dict(path=path, result=result))
        return result

    # --- reads -----------------------------------------------------------------------------

    @staticmethod
    def controller_problems(state):
        """Why the controller is not 'healthy, running, Auto'. Same test the workflow applies."""
        robot = state.get('robot') or {}
        problems = [text for bad, text in (
            (not robot.get('connected') or not robot.get('ok'), 'console is not connected to the controller'),
            (bool(robot.get('errors')), f"controller errors: {robot.get('errors')}"),
            (not robot.get('enabled'), 'robot is not enabled'),
            ((robot.get('control_mode') or {}).get('mode') != 'auto', 'controller is not in Auto'),
            ((robot.get('program_state') or {}).get('state') != 'running', 'controller program is not running'),
            (not (state.get('envelope') or {}).get('enabled'), 'workspace envelope is not enabled')) if bad]
        return problems

    def _active(self):
        sequence = self._api('seq')
        lacry = self._api('researcher/api/lacry/state')
        if sequence.get('active'):
            return f"console sequence {sequence.get('name')} is running"
        if (lacry.get('running') or {}).get('active'):
            return 'a researcher workflow is running'
        return None

    def read_status(self):
        robot = self._api('state').get('robot') or {}
        active = self._active()
        if not robot.get('ok') or not robot.get('connected'):
            state, detail = 'unknown', robot.get('error', 'console is not connected to the controller')
        elif robot.get('errors'):
            state, detail = 'error', f"controller errors: {robot['errors']}"
        elif active:
            state, detail = 'busy', active
        else:
            state, detail = 'idle', 'no console sequence running'
        return dict(state=state, detail=detail, source='operator console')

    def hamilton_problems(self):
        h = self._api('researcher/api/lacry/hamilton/status')
        return [text for bad, text in (
            (not h.get('connected'), 'Hamilton is not connected'),
            (h.get('global_state') != 'Idle', f"Hamilton is {h.get('global_state')}"),
            (h.get('parked') is not True, 'Hamilton channels are not confirmed parked'),
            (bool(h.get('pending_errors')), 'Hamilton has pending errors'),
            (bool(h.get('operation')), 'a Hamilton operation is unresolved')) if bad]

    def squid_problems(self):
        if self.squid is None:
            return ['no Squid reader configured']
        facts = self.squid.preflight()
        return [text for bad, text in (
            (not facts['stage_real'], 'Squid stage is simulated'),
            (not facts['no_scan'], 'Squid is scanning'),
            (not facts['at_target'], f"Squid stage is not at the loading position: {facts['position']}")) if bad]

    def preflight(self, params):
        """Every fact the workflow start depends on. Reads only."""
        state = self._api('state')
        facts = dict(controller=self.controller_problems(state), active=self._active(),
                     pose_mm=(state.get('robot') or {}).get('pose_mm'),
                     external_axes=(state.get('robot') or {}).get('external_axes'))
        if params.get('home_to_hamilton_roundtrip'):
            facts['hamilton'] = self.hamilton_problems()
        if params.get('home_to_squid_roundtrip'):
            facts['squid'] = self.squid_problems()
        return facts

    def check(self, text, name=None, params=None):
        params = params or {}
        try:
            if text == 'operator console running':
                return isinstance(self._api('state'), dict)
            if text == 'controller running and fault-free':
                return not self.controller_problems(self._api('state'))
            if text == 'Hamilton idle and parked and error-free when selected':
                return not params.get('home_to_hamilton_roundtrip') or not self.hamilton_problems()
            if text == 'Squid idle at the loading position when selected':
                return not params.get('home_to_squid_roundtrip') or not self.squid_problems()
            if text == 'calibration evidence fresh (30 minutes) or full_calibration selected':
                return True if params.get('full_calibration') is True else None   # receipts are the workflow's to judge
            if text == 'every selected cycle recorded as completed in run.json':
                record = self._record()
                handling = params.get('home_to_hamilton_roundtrip') or params.get('home_to_squid_roundtrip')
                return (record.get('status') == self.DONE
                        and record.get('completed_cycles') == (params.get('cycles', 1) if handling else 0))
            if text == 'plate released in HOME':
                return self._record().get('status') == self.DONE     # per the workflow's own verified receipts
        except Exception:
            return False
        return None

    # --- the workflow ------------------------------------------------------------------

    def timeout_s(self, name, params):
        """About three times the measured duration (178 s calibration, 180 s per cycle, 2026-11-11)."""
        if name != self.WORKFLOW:
            return None
        handling = params.get('home_to_hamilton_roundtrip') or params.get('home_to_squid_roundtrip')
        return 120 + (600 if params.get('full_calibration') else 0) + (600 * params.get('cycles', 1) if handling else 0)

    def argv(self, params, execute):
        unknown = set(params) - set(self.FLAGS) - {'cycles'}
        cycles = params.get('cycles', 1)
        if unknown or any(type(params.get(f, False)) is not bool for f in self.FLAGS):
            raise ValueError(f'Workflow flags must be true or false; unknown: {sorted(unknown)}')
        if type(cycles) is not int or not 1 <= cycles <= self.MAX_CYCLES:
            raise ValueError(f'cycles must be a whole number from 1 to {self.MAX_CYCLES}.')
        if not any(params.get(f) for f in self.FLAGS):
            raise ValueError('Select at least one workflow.')
        argv = [self.python, '-B', '-u', str(self.script)]
        argv += ['--' + f.replace('_', '-') for f in self.FLAGS if params.get(f)]
        if cycles != 1:
            argv += ['--cycles', str(cycles)]
        return argv + (['--execute'] if execute else [])

    def preview(self, params):
        """The workflow's own preview. Sends nothing."""
        done = subprocess.run(self.argv(params, execute=False), cwd=self.checkout, capture_output=True,
                              text=True, timeout=120, creationflags=_NO_WINDOW)
        if done.returncode:
            raise RuntimeError(f'preview failed: {done.stderr.strip()[-400:]}')
        return json.loads(done.stdout)

    def _record(self):
        return json.loads(Path(self.last_record).read_bytes()) if self.last_record else {}

    def evidence(self, name):
        return [self.last_record] if name == self.WORKFLOW and self.last_record and Path(self.last_record).exists() else []

    def collect_dataset(self, run, step, operation):
        paths = self.evidence(operation)
        if not paths or self.checkout is None:
            return []
        from .dataset import bioyond_receipt_roots
        return collect_receipts(run, 'bioyond_s4', step, paths, bioyond_receipt_roots(self.checkout))

    def run(self, name, params, timeout_s, progress=None):
        if name in self.READS:
            return self._api('state', timeout=timeout_s).get('robot') or {}
        if name != self.WORKFLOW or not self.bound(name):
            raise PermissionError(f'{name} is not wired.')
        argv = self.argv(params, execute=True)
        self.last_record, self.stop_response = None, None
        self.process = subprocess.Popen(argv, cwd=self.checkout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding='utf-8', errors='replace', bufsize=1,
                                        creationflags=_NO_WINDOW)
        lines = queue.Queue()

        def pump():
            for line in self.process.stdout:
                lines.put(line.rstrip('\r\n'))
            lines.put(None)

        threading.Thread(target=pump, daemon=True, name='plate-workflow-output').start()
        deadline = time.monotonic() + timeout_s - min(30, timeout_s * .2)   # stop it ourselves before the facade gives up
        tail = []
        while True:
            try:
                line = lines.get(timeout=.25)
            except queue.Empty:
                line = ''
            if line is None:
                break
            if time.monotonic() > deadline:
                self.abort()
                raise TimeoutError('The plate workflow did not finish in time. A stop was requested through the '
                                   'console; the phase in progress may complete.')
            if not line:
                continue
            self._journal('stdout', dict(line=line))
            try:
                parsed = json.loads(line)
            except ValueError:
                parsed = dict(text=line)
            if not isinstance(parsed, dict):
                parsed = dict(text=line)
            if parsed.get('record'):
                self.last_record = parsed['record']
            tail = (tail + [line])[-12:]
            if progress:
                progress(parsed)
        code = self.process.wait(timeout=15)
        record = self._record()
        summary = dict(record=self.last_record, status=record.get('status'),
                       completed_cycles=record.get('completed_cycles'), planned_cycles=record.get('planned_cycles'),
                       final_receipt=record.get('final_receipt'), exit_code=code)
        if code != 0:
            reason = record.get('error') or next((t for t in reversed(tail) if t.strip()), 'no output')
            raise RuntimeError(f"The plate workflow stopped (exit {code}, status {record.get('status')}): {reason}")
        return summary

    def abort(self):
        """Ask the console to stop after the step in progress, and end the launcher. Not an E-stop."""
        try:
            self.stop_response = self._api('researcher/api/lacry/stop', {})
        except Exception as error:
            self.stop_response = dict(error=str(error))
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        return dict(console_stop=self.stop_response)


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
