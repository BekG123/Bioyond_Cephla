"""run_plate_workflow through the real Bioyond backend, against a stub console and a stub CLI."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
import threading

import pytest

from labfacade import Facade, HumanConsole, Signer, load_manifests
from labfacade.backends import BioyondConsoleBackend
from conftest import REPO, FakeClock, kinds

FAKE_CHECKOUT = Path(__file__).parent / 'fixtures' / 'fake_checkout'
ASK = ('plate supported in HOME', 'destination holders empty', 'Hamilton access open', 'routes clear')
FULL = dict(full_calibration=True, home_to_hamilton_roundtrip=True, home_to_squid_roundtrip=True)


class FakeConsole:
    """Answers the console routes the backend reads, and records every request."""

    def __init__(self):
        self.robot = dict(ok=True, connected=True, errors=[], enabled=True, control_mode=dict(mode='auto'),
                          program_state=dict(state='running'), pose_mm=dict(X=1, Y=2, Z=3, Rz=4), external_axes={})
        self.envelope = dict(enabled=True)
        self.sequence_active = False
        self.hamilton = dict(connected=True, global_state='Idle', parked=True, pending_errors=[], operation=None)
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self):
                length = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                fake.requests.append((self.command, self.path, body))
                payload = {
                    '/state': dict(robot=fake.robot, envelope=fake.envelope),
                    '/seq': dict(active=fake.sequence_active, name='x'),
                    '/researcher/api/lacry/state': dict(running=dict(active=False)),
                    '/researcher/api/lacry/hamilton/status': fake.hamilton,
                    '/researcher/api/lacry/stop': dict(ok=True, stopped=True),
                }.get(self.path)
                data = json.dumps(payload).encode()
                self.send_response(200 if payload is not None else 404)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            do_GET = do_POST = reply

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def posts(self):
        return [path for method, path, _ in self.requests if method == 'POST']

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FakeSquidReader:
    def __init__(self):
        self.facts = dict(stage_real=True, no_scan=True, at_target=True, position=dict(x_mm=.5, y_mm=.5, z_mm=.064))

    def preflight(self):
        return dict(self.facts)


@pytest.fixture
def cell(tmp_path, monkeypatch):
    monkeypatch.setenv('FAKE_WORKFLOW', 'ok')
    checkout = tmp_path / 'checkout'
    shutil.copytree(FAKE_CHECKOUT, checkout)
    console, squid = FakeConsole(), FakeSquidReader()
    manifest = load_manifests(REPO / 'machines')['bioyond_s4']
    assert manifest.valid, manifest.errors
    backend = BioyondConsoleBackend(base=console.base, checkout=checkout, python=sys.executable, squid=squid)
    clock, signer = FakeClock(), Signer(b'workflow-test-key-0123456789')
    facade = Facade.from_manifests({'bioyond_s4': manifest}, {'bioyond_s4': backend}, signer, tmp_path / 'runs', clock)

    def start(params=FULL, confirm=True):
        clock.advance(1)
        run = facade.new_run(dict(title='plate workflow', plates={'P1': 'bioyond deck'}, steps=[
            dict(id='s01', machine='bioyond_s4', operation='run_plate_workflow', params=deepcopy(params),
                 transfer={'plate': 'P1', 'from': 'bioyond deck', 'to': 'bioyond deck'})]), 'workflow')
        person = HumanConsole(run, signer, clock)
        person.approve_plan('bek')
        person.attest_presence('bek')
        for text in ASK if confirm else ():
            person.confirm('s01', text, 'bek')
        return run, person

    yield dict(console=console, squid=squid, backend=backend, facade=facade, start=start, checkout=checkout)
    console.close()


def test_workflow_runs_and_every_line_is_logged(cell):
    run, _ = cell['start'](confirm=False)
    result = cell['facade'].run_step(run, 's01')
    assert (result['outcome'], sorted(result['detail']['confirm'])) == ('waiting', sorted(ASK))
    assert cell['backend'].process is None                       # nothing launched yet

    run, _ = cell['start']()
    result = cell['facade'].run_step(run, 's01')
    assert result['outcome'] == 'completed', result
    assert result['result']['status'] == BioyondConsoleBackend.DONE and result['result']['completed_cycles'] == 1
    record = json.loads(Path(result['result']['record']).read_text())
    assert record['argv'] == ['--full-calibration', '--home-to-hamilton-roundtrip', '--home-to-squid-roundtrip', '--execute']

    lines = [e['data']['line'] for e in kinds(run, 'status') if e['status'] == 'progress']
    assert lines[1] == dict(phase='Hamilton delivery', status='starting')
    assert dict(text='a line that is not JSON') in lines
    assert lines[-1]['status'] == BioyondConsoleBackend.DONE
    assert any(p.startswith('bioyond/s01/') and p.endswith('/run.json') for p in result['evidence_paths'])
    assert all((run.path / p).exists() for p in result['evidence_paths'])
    assert run.read_json('ledger.json')['plates']['P1']['location'] == 'bioyond deck'
    assert cell['console'].posts() == []                         # the facade itself posts nothing to the console


def test_cycles_flag_and_limits(cell):
    run, _ = cell['start'](dict(home_to_squid_roundtrip=True, cycles=3), confirm=False)
    person = HumanConsole(run, cell['facade']._signer, cell['facade'].clock)
    for text in ASK + ('calibration evidence fresh (30 minutes) or full_calibration selected',):
        person.confirm('s01', text, 'bek')
    result = cell['facade'].run_step(run, 's01')
    assert result['outcome'] == 'completed' and result['result']['completed_cycles'] == 3
    assert json.loads(Path(result['result']['record']).read_text())['argv'] == ['--home-to-squid-roundtrip', '--cycles', '3', '--execute']
    for params, code in ((dict(FULL, cycles=6), 'outside_limit'), (dict(FULL, speed=200), 'undeclared_parameter')):
        run, _ = cell['start'](params)
        assert cell['facade'].run_step(run, 's01')['code'] == code
    backend = cell['backend']
    assert backend.timeout_s('run_plate_workflow', FULL) == 1320
    assert backend.timeout_s('run_plate_workflow', dict(FULL, cycles=5)) == 3720
    for bad in ({}, dict(full_calibration='yes'), dict(FULL, cycles=0), dict(FULL, execute=True)):
        with pytest.raises(ValueError):
            backend.argv(bad, execute=True)


@pytest.mark.parametrize('break_it, code', [
    (lambda c: c['console'].robot.update(errors=[{'errCode': 3873}]), 'state_error'),
    (lambda c: c['console'].robot.update(connected=False), 'state_unknown'),
    (lambda c: setattr(c['console'], 'sequence_active', True), 'machine_busy'),
    (lambda c: c['console'].robot.update(enabled=False), 'precondition_not_met'),
    (lambda c: c['console'].robot.update(program_state=dict(state='paused')), 'precondition_not_met'),
    (lambda c: c['console'].envelope.update(enabled=False), 'precondition_not_met'),
    (lambda c: c['console'].hamilton.update(parked=False), 'precondition_not_met'),
    (lambda c: c['console'].hamilton.update(pending_errors=['E1']), 'precondition_not_met'),
    (lambda c: c['squid'].facts.update(no_scan=False), 'precondition_not_met'),
    (lambda c: c['squid'].facts.update(at_target=False), 'precondition_not_met'),
])
def test_nothing_is_launched_when_a_check_fails(cell, break_it, code):
    break_it(cell)
    run, _ = cell['start']()
    result = cell['facade'].run_step(run, 's01')
    assert result['code'] == code and result['outcome'] in ('waiting', 'paused')
    assert cell['backend'].process is None
    assert not (cell['checkout'] / 'operator_ui' / 'reports').exists()


def test_unselected_station_is_not_checked(cell):
    cell['console'].hamilton.update(parked=False)
    run, person = cell['start'](dict(full_calibration=True, home_to_squid_roundtrip=True))
    assert cell['facade'].run_step(run, 's01')['outcome'] == 'completed'


def test_failed_workflow_stops_the_run_and_keeps_its_record(cell, monkeypatch):
    monkeypatch.setenv('FAKE_WORKFLOW', 'fail')
    run, person = cell['start']()
    result = cell['facade'].run_step(run, 's01')
    assert (result['outcome'], result['code']) == ('failed', 'error') and 'torque band breached' in result['reason']
    assert list((run.path / 'bioyond/s01').glob('*/run.json'))
    assert run.read_json('ledger.json')['plates']['P1']['location'] == 'unknown'
    person.resume('bek', 'inspected')
    assert cell['facade'].run_step(run, 's01')['code'] == 'already_attempted'


def test_hung_workflow_is_stopped_through_the_console_and_never_relaunched(cell, monkeypatch):
    monkeypatch.setenv('FAKE_WORKFLOW', 'hang')
    monkeypatch.setattr(cell['backend'], 'timeout_s', lambda name, params: 4)
    run, person = cell['start']()
    result = cell['facade'].run_step(run, 's01')
    assert (result['outcome'], result['code']) == ('unknown', 'timeout')
    assert cell['console'].posts() == ['/researcher/api/lacry/stop']
    cell['backend'].process.wait(10)                              # the launcher was ended
    first = cell['backend'].process.pid
    person.resume('bek', 'inspected')
    assert cell['facade'].run_step(run, 's01')['code'] == 'already_attempted'
    assert cell['backend'].process.pid == first


def test_without_the_console_checkout_the_workflow_is_not_bound(cell):
    backend = BioyondConsoleBackend(base=cell['console'].base)
    assert not backend.bound('run_plate_workflow') and backend.bound('get_status')


def test_preview_sends_nothing(cell):
    assert cell['backend'].preview(FULL) == dict(motion_started=False, handling_cycles=1)
    assert cell['console'].requests == []
