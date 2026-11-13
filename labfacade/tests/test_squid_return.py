"""Squid return_to_loading through the real backend, against a local fake Squid server."""
from copy import deepcopy
import hashlib
import json
import socketserver
import threading
import time

import pytest

from labfacade import Facade, HumanConsole, Signer, load_manifests
from labfacade.backends import SquidBackend
from labfacade.manifest import Manifest
from conftest import REPO, FakeClock, kinds

TARGET = dict(x_mm=0.5000625, y_mm=0.5000625, z_mm=0.063984375)
REFERENCE = dict(schema_version=1, controller_serial='12769210', stage_simulated=False, dropoff=TARGET,
                 operator_confirmed=True)
CONFIRM = ('robot is at Home', 'stage path is clear', 'robot at Home within 0.2 mm')


def fingerprint(ref):
    return hashlib.sha256(json.dumps(ref, sort_keys=True, allow_nan=False).encode()).hexdigest()


class FakeSquid:
    """Speaks Squid's newline JSON protocol on loopback and records every command."""

    def __init__(self):
        self.position = dict(x_mm=40.0, y_mm=30.0, z_mm=1.0)
        self.reference = deepcopy(REFERENCE)
        self.simulated, self.scanning, self.confirm, self.hang = False, False, True, 0
        self.lands_at = dict(TARGET)
        self.commands = []
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                request = json.loads(self.rfile.readline())
                fake.commands.append(request)
                try:
                    reply = dict(success=True, result=fake.answer(request['command'], request['params']))
                except Exception as error:
                    reply = dict(success=False, error=str(error))
                self.wfile.write((json.dumps(reply) + '\n').encode())

        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, command, params):
        if command == 'ping':
            return dict(status='ok')
        if command == 'get_acquisition_status':
            return dict(in_progress=self.scanning, status='running' if self.scanning else 'idle')
        if command == 'get_position':
            return dict(self.position)
        if command == 'get_stage_reference':
            return dict(controller_serial='12769210', stage_simulated=self.simulated,
                        reference_hash=fingerprint(self.reference), dropoff=self.reference['dropoff'])
        if command == 'return_to_recorded_dropoff':
            if params.get('reference_hash') != fingerprint(self.reference):
                raise ValueError('Squid loading reference changed.')
            time.sleep(self.hang)
            self.position = dict(self.lands_at)
            return dict(at_dropoff=self.confirm, position=dict(self.position))
        raise ValueError(f'unknown command {command}')

    def sent(self):
        return [c['command'] for c in self.commands]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def cell(tmp_path):
    squid = FakeSquid()
    reference = tmp_path / 'squid_stage_reference.json'
    reference.write_text(json.dumps(REFERENCE))
    real = load_manifests(REPO / 'machines')['squid']
    assert real.valid, real.errors
    data = deepcopy(real.data)
    next(op for op in data['operations'] if op['name'] == 'return_to_loading')['timeout_s'] = 3
    manifest = Manifest(real.path, data, real.sha256, [])
    clock, signer = FakeClock(), Signer(b'squid-test-key-0123456789')
    backend = SquidBackend(port=squid.port, reference=reference, sleep=lambda s: None)
    facade = Facade.from_manifests({'squid': manifest}, {'squid': backend}, signer, tmp_path / 'runs', clock)
    run = facade.new_run(dict(title='stage to loading', steps=[
        dict(id='s01', machine='squid', operation='return_to_loading', params={})]), 'squid-return')
    person = HumanConsole(run, signer, clock)
    person.approve_plan('bek')
    person.attest_presence('bek')
    yield dict(squid=squid, facade=facade, run=run, person=person, reference=reference, backend=backend)
    squid.close()


def confirm_all(cell):
    for text in CONFIRM:
        cell['person'].confirm('s01', text, 'bek')


def test_stage_returns_to_loading_and_is_verified(cell):
    result = cell['facade'].run_step(cell['run'], 's01')
    assert (result['outcome'], sorted(result['detail']['confirm'])) == ('waiting', sorted(CONFIRM))
    assert 'return_to_recorded_dropoff' not in cell['squid'].sent()
    confirm_all(cell)
    result = cell['facade'].run_step(cell['run'], 's01')
    assert result['outcome'] == 'completed' and result['result']['moved'] is True
    moves = [c for c in cell['squid'].commands if c['command'] == 'return_to_recorded_dropoff']
    assert moves == [dict(command='return_to_recorded_dropoff', params=dict(reference_hash=fingerprint(REFERENCE)))]
    assert cell['squid'].position == TARGET
    assert [e['status'] for e in kinds(cell['run'], 'result')][-1] == 'completed'


def test_already_at_loading_sends_no_move(cell):
    cell['squid'].position = dict(TARGET, x_mm=TARGET['x_mm'] + .015)
    confirm_all(cell)
    result = cell['facade'].run_step(cell['run'], 's01')
    assert result['outcome'] == 'completed' and result['result']['moved'] is False
    assert 'return_to_recorded_dropoff' not in cell['squid'].sent()


@pytest.mark.parametrize('break_it, code', [
    (lambda c: setattr(c['squid'], 'scanning', True), 'machine_busy'),
    (lambda c: setattr(c['squid'], 'simulated', True), 'precondition_not_met'),
    (lambda c: c['reference'].write_text(json.dumps(dict(REFERENCE, dropoff=dict(TARGET, x_mm=5.0)))),
     'precondition_not_met'),
    (lambda c: c['reference'].write_text(json.dumps(dict(REFERENCE, controller_serial='999'))),
     'precondition_not_met'),
    (lambda c: c['reference'].write_text(json.dumps(dict(REFERENCE, operator_confirmed=False))),
     'precondition_not_met'),
    (lambda c: c['reference'].write_text(json.dumps(dict(REFERENCE, motion_hold='Stage held for service.'))),
     'precondition_not_met'),
    (lambda c: c['reference'].write_text(json.dumps(dict(REFERENCE, dropoff=dict(TARGET, x_mm=-1.0)))),
     'precondition_not_met'),
])
def test_guard_trips_before_any_move(cell, break_it, code):
    break_it(cell)
    confirm_all(cell)
    result = cell['facade'].run_step(cell['run'], 's01')
    assert (result['outcome'], result['code']) == ('waiting', code)
    assert 'return_to_recorded_dropoff' not in cell['squid'].sent()


def test_unconfirmed_or_misplaced_move_stops_the_run(cell):
    cell['squid'].lands_at = dict(TARGET, y_mm=TARGET['y_mm'] + .05)
    confirm_all(cell)
    result = cell['facade'].run_step(cell['run'], 's01')
    assert (result['outcome'], result['code']) == ('failed', 'error') and 'not at the loading position' in result['reason']
    assert cell['facade'].run_step(cell['run'], 's01')['code'] == 'run_paused'
    assert cell['squid'].sent().count('return_to_recorded_dropoff') == 1


def test_squid_not_confirming_is_a_failure(cell):
    cell['squid'].confirm = False
    confirm_all(cell)
    assert cell['facade'].run_step(cell['run'], 's01')['outcome'] == 'failed'
    assert cell['squid'].sent().count('return_to_recorded_dropoff') == 1


def test_no_reply_is_unknown_and_never_resent(cell):
    cell['squid'].hang = 4
    confirm_all(cell)
    result = cell['facade'].run_step(cell['run'], 's01')
    assert (result['outcome'], result['code']) == ('unknown', 'timeout')
    cell['person'].resume('bek', 'inspected the stage')
    assert cell['facade'].run_step(cell['run'], 's01')['code'] == 'already_attempted'
    assert cell['squid'].sent().count('return_to_recorded_dropoff') == 1


def test_only_named_commands_reach_squid(cell):
    backend = cell['backend']
    for command in ('python_exec', 'move_to', 'home', 'run_acquisition', 'abort_acquisition'):
        assert not backend.bound(command)
        with pytest.raises(PermissionError):
            backend._command(command, 1)
    assert cell['squid'].commands == []
