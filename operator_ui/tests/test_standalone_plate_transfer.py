"""Standalone transfer tests: no console server and no hardware networking."""
import json
from pathlib import Path
import signal
import socket
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_plate_transfer as cli
import standalone_plate_transfer as standalone
from autonomy import TransferError


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(socket, 'create_connection', Mock(side_effect=AssertionError('No hardware or console networking')))
    monkeypatch.setattr(cli, 'api', Mock(side_effect=AssertionError('Standalone must not call Flask')))
    monkeypatch.setattr(standalone, 'ROOT', tmp_path)


def args(destination='squid', roundtrip=False):
    return cli.parse_args(['--to', destination, '--execute'] + (['--roundtrip'] if roundtrip else []))


def harness(tmp_path, destination='squid', roundtrip=False):
    backend = SimpleNamespace(s=Mock(), params=Mock(), cam=None)
    backend.s.connect.return_value = dict(ok=True)
    backend.s.program.return_value = dict(ok=True)
    registry = Mock()
    adapter = Mock()
    adapter.preview.return_value = dict(destination=destination.title(), roundtrip=roundtrip)
    names = ['retrieve_hotel', 'register_barcode', ('roundtrip_' if roundtrip else 'deliver_') + destination]
    adapter.steps.return_value = [dict(id=n, label=n) for n in names]
    receipts = [dict(ok=True, record='hotel'), dict(ok=True, record='scan', plate_id='001'),
                dict(ok=True, record='station', plate_id='001')]
    adapter.execute_step.side_effect = receipts
    adapter.require.side_effect = standalone.HotelSquidAdapter.require
    adapter.registry.return_value = registry
    factory = Mock(return_value=adapter)
    options = dict(backend_factory=Mock(return_value=backend), registry_factory=lambda: registry,
                   adapter_factory=factory, station_check=Mock(), owner_check=Mock(), folder=tmp_path/'runs')
    return backend, registry, adapter, receipts, factory, options


@pytest.mark.parametrize('destination', ['squid', 'hamilton'])
@pytest.mark.parametrize('roundtrip', [False, True])
def test_default_cli_runs_directly_with_no_console(monkeypatch, destination, roundtrip):
    direct = Mock(return_value=dict(ok=True))
    monkeypatch.setattr(standalone, 'execute', direct)
    a = args(destination, roundtrip)
    assert not a.via_console
    assert cli.execute(a) == dict(ok=True)
    direct.assert_called_once_with(a)
    cli.api.assert_not_called()


@pytest.mark.parametrize('destination', ['squid', 'hamilton'])
@pytest.mark.parametrize('roundtrip', [False, True])
def test_direct_chain_connects_once_preserves_receipts_and_disconnects(tmp_path, destination, roundtrip):
    backend, registry, adapter, receipts, factory, options = harness(tmp_path, destination, roundtrip)
    previous = signal.getsignal(signal.SIGINT)
    result = standalone.execute(args(destination, roundtrip), **options)
    backend.s.connect.assert_called_once()
    backend.s.disconnect.assert_called_once()
    backend.s.program.assert_not_called()
    assert factory.call_args.kwargs['backend'] is backend
    assert factory.call_args.kwargs['station_check'] is options['station_check']
    calls = adapter.execute_step.call_args_list
    assert calls[0].args[3] is None and calls[1].args[3] == receipts[0] and calls[2].args[3] == receipts[1]
    assert not (options['folder']/'unresolved.json').exists()
    record = json.loads(Path(result['record']).read_text())
    assert record['console_required'] is False and record['transport'] == 'direct'
    assert record['plate_destination'] == ('HOME' if roundtrip else destination.title())
    assert record['operator_observation'] == 'pending'
    assert signal.getsignal(signal.SIGINT) == previous
    registry.record_run.assert_called_once_with('001', result['run_id'], 'completed', result['record'])


@pytest.mark.parametrize('phase', [0, 1, 2])
def test_failed_phase_stops_retains_latch_and_never_dispatches_successor(tmp_path, phase):
    backend, registry, adapter, receipts, _, options = harness(tmp_path)
    adapter.execute_step.side_effect = receipts[:phase] + [TimeoutError('unknown result')]
    with pytest.raises(TimeoutError):
        standalone.execute(args(), **options)
    assert adapter.execute_step.call_count == phase+1
    backend.s.connect.assert_called_once();backend.s.disconnect.assert_called_once()
    backend.s.program.assert_called_once_with('stop')
    hold = json.loads((options['folder']/'unresolved.json').read_text())
    record = json.loads(Path(hold['record']).read_text())
    assert record['status'] == 'stopped_or_uncertain'
    with pytest.raises(TransferError, match='unresolved'):
        standalone.execute(args(), **options)
    backend.s.connect.assert_called_once()


def test_preflight_refusal_disconnects_without_motion_or_retained_latch(tmp_path):
    backend, _, adapter, _, _, options = harness(tmp_path)
    adapter.preview.side_effect = TransferError('Already-running healthy Auto required')
    with pytest.raises(TransferError):standalone.execute(args(), **options)
    adapter.execute_step.assert_not_called();backend.s.program.assert_not_called()
    backend.s.disconnect.assert_called_once()
    assert not (options['folder']/'unresolved.json').exists()
    assert next(options['folder'].glob('*.json')).read_text().find('refused_before_dispatch') >= 0


def test_existing_owner_or_experiment_blocks_before_connection(tmp_path):
    backend, _, _, _, _, options = harness(tmp_path)
    options['owner_check'].side_effect = TransferError('another client owns connection')
    with pytest.raises(TransferError):standalone.execute(args(), **options)
    options['backend_factory'].assert_not_called();backend.s.connect.assert_not_called()
    lease = tmp_path/'runs/experiments/.supervised-lab-lease.json'
    lease.parent.mkdir(parents=True, exist_ok=True);lease.write_text('{}')
    with pytest.raises(TransferError, match='experiment owns'):
        standalone.execute(args(), **options)
    options['backend_factory'].assert_not_called()


def test_socket_owner_detection_never_opens_a_connection(monkeypatch):
    import psutil
    peer = SimpleNamespace(ip='192.168.201.220', port=56788)
    query = Mock(return_value=[SimpleNamespace(raddr=peer, status=psutil.CONN_ESTABLISHED, pid=123)])
    monkeypatch.setattr(psutil, 'net_connections', query)
    with pytest.raises(TransferError, match='123'):
        standalone.assert_robot_available(peer.ip, peer.port)
    socket.create_connection.assert_not_called()


def test_cancellation_between_phases_never_starts_next_phase(tmp_path):
    backend, _, adapter, receipts, _, options = harness(tmp_path)
    run = standalone.TerminalRun('test')
    options['run_factory'] = lambda ident: run
    def first(*_):
        run.cancel.set()
        return receipts[0]
    adapter.execute_step.side_effect = first
    with pytest.raises(TransferError, match='stopped'):
        standalone.execute(args(), **options)
    adapter.execute_step.assert_called_once()
    backend.s.program.assert_called_once_with('stop')
    assert (options['folder']/'unresolved.json').exists()


def test_logging_failure_cannot_dispatch_motion(tmp_path, monkeypatch):
    backend, _, adapter, _, _, options = harness(tmp_path)
    original = standalone.write_run_record
    def write(path, record):
        if record['steps'] and record['steps'][-1]['status'] == 'dispatching' and record['status'] == 'running':
            raise OSError('disk failure before dispatch')
        original(path, record)
    monkeypatch.setattr(standalone, 'write_run_record', write)
    with pytest.raises(OSError):standalone.execute(args(), **options)
    adapter.execute_step.assert_not_called()
    backend.s.program.assert_not_called();backend.s.disconnect.assert_called_once()


def test_hamilton_status_uses_native_adapter_and_original_readiness_rules(tmp_path, monkeypatch):
    from hamilton_prep import HamiltonPrep
    import cellvis24_hamilton_route as route
    monkeypatch.setattr(route, 'urlopen', Mock(side_effect=AssertionError('No console HTTP')))
    values = {'instruments/connection-info':['Connected: True', 'Serial Number: PRPGJ2494', 'Initialization Status: Initialized'],
              'instruments/global-run-state':'Idle', 'protocol-run':None,
              'errors/check-for-pending-errors':False, 'protocols':[], 'service-software-api/is-parked':True}
    def request(method, path, body):
        assert method == 'GET' and body is None
        return values[path]
    check = standalone.StationChecks()
    check.hamilton = HamiltonPrep(request=request, folder=tmp_path)
    assert check('hamilton', {})['parked'] is True
    values['service-software-api/is-parked'] = False
    with pytest.raises(TransferError, match='parked'):check('hamilton', {})
    (tmp_path/'active.json').write_text('{}')
    with pytest.raises(TransferError, match='owned or unresolved'):check('hamilton', {})


@pytest.mark.parametrize('destination', ['squid', 'hamilton'])
def test_actual_station_planner_and_executor_use_injected_readiness(tmp_path, monkeypatch, destination):
    import cellvis24_workflow as workflow
    g = workflow.geometry()
    source = tmp_path/'home.json';source.write_text('{}')
    state = dict(pose_mm=g['clearance'], joints=dict(J1=100,J2=1,J3=2,J4=3))
    native = dict(moving=False,external_axes=dict(E1=28,E2=1.77))
    monkeypatch.setattr(workflow,'preflight',lambda service:state)
    monkeypatch.setattr(workflow,'native',lambda service:native)
    monkeypatch.setattr(workflow,'source_record',lambda path:(source,dict(final=state)))
    monkeypatch.setattr(workflow,'validate_steps',Mock())
    monkeypatch.setattr(workflow,'RUNS',tmp_path/'runs')
    monkeypatch.setattr(workflow,'hamilton_ready',Mock(side_effect=AssertionError('Console readiness forbidden')))
    monkeypatch.setattr(workflow,'squid_ready',Mock(side_effect=AssertionError('Default readiness forbidden')))
    service=Mock(envelope=g['envelope'])
    check=Mock(return_value={})
    options={'recorded_hamilton_variant':'opposite3'} if destination=='hamilton' else {}
    plan=workflow.plan(service,g['cfg'],[destination],1,source=source,probe=False,station_check=check,**options)
    check.assert_called_once_with(destination,g)
    # Exercise real execution dispatch using an instrument-only test plan.
    plan['steps']=[dict(kind='instrument',label='Check destination before delivery',station=destination,cycle=1)]
    run=Mock();run.stopped.return_value=False
    result=workflow.execute_checked_steps(run,service,g['cfg'],plan,plan,ends_held=False,station_check=check)
    assert result['ok'] and check.call_count==2
    service.move_gripper.assert_not_called();service.robot.set_sys_var_i.assert_not_called()


def test_adapter_injects_direct_checks_through_station_delivery(monkeypatch):
    import composed_cellvis_registration as registration
    import cellvis24_workflow as workflow
    checker=Mock();backend=Mock();registry=Mock()
    adapter=standalone.HotelSquidAdapter(backend=backend,registry=registry,station_check=checker)
    spec=dict(destination='Hamilton',roundtrip=True,continuation=dict(acceptance='hash',delivery_steps=[]))
    monkeypatch.setattr(workflow,'evidence',lambda:'hash')
    deliver=Mock(return_value=dict(ok=True));monkeypatch.setattr(registration,'deliver',deliver)
    adapter.execute_step(Mock(),spec,'roundtrip_hamilton',dict(record='scan'))
    assert deliver.call_args.kwargs['station_check'] is checker
    assert adapter.registry() is registry
