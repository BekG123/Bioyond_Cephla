"""Direct, foreground owner for accepted Cellvis hotel/scanner/station workflows.

No Flask application, Lacry agent, HTTP self-dispatch or background console is
created. Only the existing robot and instrument transports contact hardware.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from autonomy import TransferError
from hotel_squid_composition import HotelSquidAdapter
from run_record_io import write_run_record

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'runs' / 'composed_transfers'


def assert_robot_available(host, port):
    """Never displace another local owner of the single-client BRCAPI socket."""
    import psutil
    for connection in psutil.net_connections(kind='tcp'):
        peer = connection.raddr
        if (peer and peer.ip == host and peer.port == port
                and connection.status != psutil.CONN_TIME_WAIT):
            raise TransferError(
                f'Robot connection is already owned by process {connection.pid}. '
                'Disconnect that client (console, MCP or Bioyond Works) before standalone execution.')


class StationChecks:
    """Read instrument readiness directly, using the existing validation rules."""
    def __init__(self):
        self.hamilton = None

    def __call__(self, station, geometry):
        if station == 'squid':
            from cellvis24_squid_route import instrument_ready
            return instrument_ready(geometry)  # Squid's own TCP server, port 5050.
        if station != 'hamilton':
            raise TransferError('Unknown station readiness check.')
        from hamilton_prep import HamiltonPrep
        from cellvis24_hamilton_route import validate_instrument_state
        if self.hamilton is None:
            self.hamilton = HamiltonPrep()
        if any((self.hamilton.folder / name).exists() for name in ('active.json', 'dcg48_execution.lock')):
            raise TransferError('Hamilton has an owned or unresolved operation; inspect it before handling.')
        return validate_instrument_state(self.hamilton.status(fresh=True))


class TerminalRun:
    def __init__(self, run_id, clock=time.monotonic):
        self.run_id = run_id
        self.cancel = threading.Event()
        self.clock = clock
        self.started = clock()

    def stopped(self):
        return self.cancel.is_set() or self.clock() - self.started > 900

    def say(self, message, level='info'):
        print(json.dumps(dict(run_id=self.run_id, level=level, message=message)), flush=True)

    def audit(self, event, **fields):
        print(json.dumps(dict(run_id=self.run_id, event=event, **fields), default=str), flush=True)


@contextmanager
def cancellation(run):
    previous = signal.getsignal(signal.SIGINT)
    def stop(_signal, _frame):
        run.cancel.set()
    signal.signal(signal.SIGINT, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def make_backend():
    from robot_service import RobotService
    from sequences import get_robot_params
    from draggo import DragGo
    service = RobotService()
    service.draggo_guard = DragGo(lambda: service, ROOT / 'operator_ui/demonstrations/draggo-active.json')
    return SimpleNamespace(s=service, params=get_robot_params, cam=None)


def execute(args, *, backend_factory=make_backend, registry_factory=None,
            adapter_factory=HotelSquidAdapter, station_check=None,
            owner_check=assert_robot_available, folder=REPORTS, run_factory=TerminalRun):
    """Connect once, execute predecessor-bound phases once, then disconnect.

Factories are for offline tests; no CLI arguments allow replacing executors,
coordinates, station checks, acceptance evidence or source receipts.
"""
    from plate_registry import PlateRegistry
    from robot_service import DEFAULT_IP, DEFAULT_PORT
    if not args.execute:
        raise ValueError('Standalone execution requires --execute.')
    folder = Path(folder)
    # Share the existing persistent uncertainty latch with console compositions.
    folder.mkdir(parents=True, exist_ok=True)
    hold = folder / 'unresolved.json'
    if hold.exists():
        raise TransferError(f'An active or unresolved transfer owns {hold}; inspect its record. No automatic retry.')
    experiment_lease = ROOT / 'runs/experiments/.supervised-lab-lease.json'
    if experiment_lease.exists():
        raise TransferError('A supervised experiment owns the lab; inspect its retained lease first.')
    ident = uuid4().hex
    path = folder / (ident + '.json')
    run = run_factory(ident)
    record = dict(id=ident, status='preflight', transport='direct', console_required=False,
                  source_slot=args.source_slot, destination=args.destination.title(),
                  roundtrip=args.roundtrip, expected_plate_id=args.expected_plate_id,
                  started_at=time.time(), steps=[], operator_observation='pending',
                  automatic_retries=False, approval_source='terminal_execute_flag')
    # Acquire before opening any device. A killed process leaves visible evidence.
    with hold.open('x', encoding='utf-8') as stream:
        json.dump(dict(record=str(path), run_id=ident, pid=os.getpid(), transport='direct'), stream)
        stream.flush()
        os.fsync(stream.fileno())
    backend = None
    adapter = None
    prior = None
    attempted = False
    result = None
    def save():
        write_run_record(path, record)
    try:
        with cancellation(run):
            save()
            owner_check(DEFAULT_IP, DEFAULT_PORT)
            if run.stopped():
                raise TransferError('Stopped before connecting to the robot.')
            backend = backend_factory()
            HotelSquidAdapter.require(backend.s.connect(DEFAULT_IP, DEFAULT_PORT))
            record['connection'] = dict(host=DEFAULT_IP, port=DEFAULT_PORT)
            registry = (registry_factory or PlateRegistry)()
            adapter = adapter_factory(backend=backend, registry=registry,
                                      station_check=station_check if station_check is not None else StationChecks())
            spec = adapter.preview(args.expected_plate_id, args.source_slot,
                                   args.destination.title(), 'Cellvis P24-1.5H-N', args.roundtrip)
            steps = adapter.steps(spec)
            record.update(status='running', plan=spec)
            save()
            print(json.dumps(dict(run_id=ident, record=str(path), transport='direct',
                                  steps=steps, confirmation='--execute')), flush=True)
            for step in steps:
                if run.stopped():
                    raise TransferError('Transfer stopped or the 15-minute supervision window elapsed; no retry.')
                item = dict(step=step['id'], status='dispatching')
                record['steps'].append(item)
                save()  # Durable intent precedes each phase that may move hardware.
                run.say(step['label'])
                attempted = True
                prior = adapter.require(adapter.execute_step(run, spec, step['id'], prior))
                item.update(status='completed', result=prior)
                save()
            plate_id = prior.get('plate_id') or args.expected_plate_id
            if plate_id:
                registry.record_run(plate_id, ident, 'completed', str(path))
            record.update(status='completed_controller_verified', plate_id=plate_id,
                          plate_destination='HOME' if args.roundtrip else args.destination.title(),
                          finished_at=time.time())
            save()
            hold.unlink()
            result = dict(ok=True, run_id=ident, record=str(path), status=record['status'],
                          plate_id=plate_id, plate_destination=record['plate_destination'])
    except BaseException as error:
        run.cancel.set()
        record.update(status='stopped_or_uncertain' if attempted else 'refused_before_dispatch',
                      error=str(error) or type(error).__name__, finished_at=time.time())
        if attempted and backend is not None:
            # Never reconnect/restart/resend a motion. Stop is best-effort only.
            try:
                record['stop_response'] = backend.s.program('stop')
            except Exception as stop_error:
                record['stop_error'] = str(stop_error)
            plate_id = (prior or {}).get('plate_id') or args.expected_plate_id
            if plate_id and adapter is not None:
                try:
                    adapter.registry().record_run(plate_id, ident, 'unknown', str(path))
                except Exception as registry_error:
                    record['registry_error'] = str(registry_error)
        save()
        if not attempted:
            hold.unlink()
        raise
    finally:
        if backend is not None:
            try:
                backend.s.disconnect()
            except Exception as error:
                run.say('Robot disconnect could not be confirmed: ' + str(error), 'error')
        print(json.dumps(dict(status=record['status'], record=str(path))), flush=True)
    return result
