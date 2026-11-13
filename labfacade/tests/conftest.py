from copy import deepcopy
from pathlib import Path
import sys
import socket

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from labfacade import Facade, HumanConsole, Signer, load_manifests  # noqa: E402
from labfacade.fakes import FakeMachine  # noqa: E402

FIXTURES = Path(__file__).parent / 'fixtures' / 'machines'
SCHEMA = REPO / 'machines' / 'manifest.schema.json'


@pytest.fixture(autouse=True)
def no_live_hardware(monkeypatch, tmp_path):
    """Tests may use ephemeral localhost stub servers, never the lab services."""
    original = socket.socket.connect
    def guarded(sock, address):
        if isinstance(address, tuple) and (address[0] not in ('127.0.0.1', 'localhost', '::1') or address[1] in (5002, 5050, 56788, 2000)):
            raise RuntimeError(f'Live hardware/network connection prohibited in tests: {address}')
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', guarded)
    monkeypatch.setenv('SQUID_SOFTWARE_DIR', str(tmp_path / 'unconfigured-squid'))

PLAN = dict(title='plate to squid', plates={'P1': 'gripper'}, steps=[
    dict(id='s01', machine='squid', operation='return_to_loading', params={}),
    dict(id='s02', machine='bioyond_s4', operation='place_plate', params={'station': 'squid'},
         transfer={'plate': 'P1', 'from': 'gripper', 'to': 'squid stage'}),
    dict(id='s03', machine='squid', operation='run_imaging', params={}),
    dict(id='s04', machine='hamilton_prep', operation='park', params={}),
])


class FakeClock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Lab:
    """Three fake machines behind a facade, plus the person's console."""

    def __init__(self, root):
        self.clock = FakeClock()
        self.signer = Signer(b'test-key-0123456789abcdef')
        self.manifests = load_manifests(FIXTURES, SCHEMA)
        assert all(m.valid for m in self.manifests.values()), {k: m.errors for k, m in self.manifests.items()}
        self.fakes = dict(
            hamilton_prep=FakeMachine(clock=self.clock, sensors={'door_closed': True},
                                      conditions={'initialized': True, 'parked': True}),
            bioyond_s4=FakeMachine(clock=self.clock, conditions={'plate released': True}),
            squid=FakeMachine(clock=self.clock, conditions={'no scan running': True, 'at loading position': True,
                                                            'acquisition complete': True}))
        self.facade = Facade.from_manifests(self.manifests, self.fakes, self.signer, root / 'runs', self.clock)

    def run(self, plan=None, approve=True, attest=True):
        run = self.facade.new_run(deepcopy(plan or PLAN), 'test')
        console = HumanConsole(run, self.signer, self.clock)
        if approve:
            console.approve_plan('bek')
        if attest:
            console.attest_presence('bek')
        return run, console

    def one_step(self, machine, operation, params=None, **extra):
        return dict(title='one step', plates={'P1': 'gripper'},
                    steps=[dict(id='s01', machine=machine, operation=operation, params=params or {}, **extra)])

    def sent(self, machine):
        return [c['name'] for c in self.fakes[machine].commands]


@pytest.fixture
def lab(tmp_path):
    return Lab(tmp_path)


def kinds(run, kind):
    return [e for e in run.events.read() if e['kind'] == kind]
