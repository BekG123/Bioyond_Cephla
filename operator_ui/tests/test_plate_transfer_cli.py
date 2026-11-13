"""Offline terminal/API tests; hardware networking is forbidden."""
from copy import deepcopy
import ast
import json
import io
from pathlib import Path
import socket
import sys
import threading
import time
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from flask import Blueprint, Flask, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_plate_transfer as cli
import composed_cellvis_registration as registration
from hotel_squid_composition import HotelSquidAdapter
from lacry_workflow_composition import WorkflowComposition, composition_outline
from researcher_teaching import TeachingError
from test_lacry_workflow_composition import agent


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', Mock(side_effect=AssertionError('Hardware networking forbidden')))


@pytest.mark.parametrize('destination', ['squid', 'hamilton'])
@pytest.mark.parametrize('roundtrip', [False, True])
def test_all_offline_previews_preserve_accepted_routes(destination, roundtrip, monkeypatch):
    network = Mock(side_effect=AssertionError('Preview must not call the console'))
    monkeypatch.setattr(cli, 'api', network)
    args = ['--destination', destination] + (['--roundtrip'] if roundtrip else [])
    result = cli.main(args)
    assert result['motion_started'] is False and result['scanner_z'] == 163.76
    assert result['finish'] == dict(plate='HOME' if roundtrip else destination.title(), arm='HOME')
    assert [s['id'] for s in result['steps']] == ['retrieve_hotel', 'register_barcode',
        ('roundtrip_' if roundtrip else 'deliver_') + destination]
    from cellvis24_workflow import compile_steps
    options = {'recorded_hamilton_variant': 'opposite3'} if destination == 'hamilton' else {}
    original = compile_steps([destination], 1, **options)
    cut = next(i for i, s in enumerate(original) if s['label'] == 'Check destination before retrieval')
    assert registration.delivery_steps(destination.title(), roundtrip) == (original if roundtrip else original[:cut])
    network.assert_not_called()


@pytest.mark.parametrize('args', [[], ['--to','unknown'], ['--to','squid','--source-slot','2'],
    ['--to','squid','--roundtrip','--drop-off'], ['--to','squid','--expected-plate-id','']])
def test_invalid_arguments_never_dispatch(args, monkeypatch):
    call = Mock();monkeypatch.setattr(cli, 'api', call)
    with pytest.raises(SystemExit):cli.parse_args(args)
    call.assert_not_called()


@pytest.mark.parametrize('failure', ['lost_start', 'failed_step', 'lost_poll', 'interrupt'])
def test_cli_never_retries_and_stops_only_its_plan(failure, monkeypatch):
    calls = []
    ident = 'a'*32
    def api(path, body=None):
        calls.append((path, body))
        if path == 'plan':return dict(ok=True, plan=dict(id=ident, executable=True))
        if path == 'start':
            if failure == 'lost_start':raise TimeoutError('ACK lost')
            return dict(ok=True, plan_id=ident)
        if path.startswith('status/'):
            if failure == 'lost_poll':raise TimeoutError('poll lost')
            if failure == 'interrupt':raise KeyboardInterrupt()
            return dict(ok=True, plan_id=ident, status='stopped_or_uncertain', record='failed.json', error='scanner error')
        if path == 'stop':return dict(ok=True)
        raise AssertionError(path)
    monkeypatch.setattr(cli, 'api', api)
    with pytest.raises((RuntimeError, TimeoutError, KeyboardInterrupt)):
        cli.execute(cli.parse_args(['--to','hamilton','--roundtrip','--execute','--via-console']))
    assert sum(path == 'start' for path, _ in calls) == 1
    assert calls[-1] == ('stop', dict(plan_id=ident))


def test_cli_success_preserves_exact_barcode_and_mode(monkeypatch):
    calls=[];ident='b'*32
    def api(path,body=None):
        calls.append((path,body))
        if path=='plan':return dict(ok=True,plan=dict(id=ident,executable=True))
        if path=='start':return dict(ok=True,plan_id=ident)
        return dict(ok=True,plan_id=ident,status='completed_controller_verified',record='run.json')
    monkeypatch.setattr(cli,'api',api)
    assert cli.execute(cli.parse_args(['--to','squid','--expected-plate-id',' 001 ','--execute','--via-console']))['record']=='run.json'
    assert calls[0]==('plan',dict(destination='Squid',roundtrip=False,plate_id=' 001 '))
    assert all(path!='stop' for path,_ in calls)


@pytest.mark.parametrize('destination',['Squid','Hamilton'])
@pytest.mark.parametrize('roundtrip',[False,True])
def test_shared_composition_preserves_receipts_and_final_custody(tmp_path,destination,roundtrip):
    a=agent();adapter=Mock();spec=dict(plate_id=None,slot=1,destination=destination,roundtrip=roundtrip)
    adapter.preview.return_value=spec
    adapter.steps.return_value=composition_outline('Cellvis P24-1.5H-N',1,destination,roundtrip)[0]
    adapter.require.side_effect=HotelSquidAdapter.require
    receipts=[dict(ok=True,record='hotel'),dict(ok=True,record='barcode',plate_id='001'),
              dict(ok=True,record='station',plate_id='001')]
    adapter.execute_step.side_effect=receipts
    composition=WorkflowComposition(a,adapter,tmp_path)
    composition.propose('Cellvis P24-1.5H-N',1,destination,roundtrip=roundtrip)
    run=Mock();run.stopped.return_value=False
    composition.execute(run,deepcopy(a.pending),tmp_path/'run.json')
    assert adapter.execute_step.call_args_list[1].args[3]==receipts[0]
    assert adapter.execute_step.call_args_list[2].args[3]==receipts[1]
    record=json.loads((tmp_path/'run.json').read_text())
    assert record['plate_destination']==('HOME' if roundtrip else destination)
    assert record['plate_id']=='001' and record['operator_observation']=='pending'


def client(tmp_path):
    from plate_transfer_api import register
    a=agent();a.busy=False;a.run_meta={}
    adapter=Mock();a.workflow_composition=WorkflowComposition(a,adapter,tmp_path)
    app=Flask(__name__);bp=Blueprint('transfer',__name__)
    register(bp,lambda:a);app.register_blueprint(bp)
    @app.errorhandler(TeachingError)
    def error(e):return jsonify(ok=False,message=str(e)),e.status
    c=app.test_client();c.environ_base['HTTP_X_CEPHLA_TERMINAL']='plate-transfer-v1'
    return c,a,adapter


def test_terminal_endpoint_binds_approval_once_and_refuses_stale_id(tmp_path):
    c,a,adapter=client(tmp_path)
    adapter.preview.return_value=dict(plate_id=None,slot=1,destination='Hamilton',roundtrip=True)
    adapter.steps.return_value=composition_outline('Cellvis P24-1.5H-N',1,'Hamilton',True)[0]
    reply=c.post('/plate-transfer/plan',json=dict(destination='Hamilton',roundtrip=True))
    assert reply.status_code==200
    ident=reply.json['plan']['id']
    assert c.post('/plate-transfer/start',json=dict(plan_id='a'*32,ready=True)).status_code!=200
    assert c.post('/plate-transfer/start',json=dict(plan_id=ident,ready=False)).status_code==400
    a.get_runner.return_value.start.return_value=dict(ok=True)
    assert c.post('/plate-transfer/start',json=dict(plan_id=ident,ready=True)).json['plan_id']==ident
    assert a.pending is None
    assert c.post('/plate-transfer/start',json=dict(plan_id=ident,ready=True)).status_code!=200
    saved=json.loads((tmp_path/(ident+'.json')).read_text())
    assert saved['plan']['confirmation_source']=='researcher_terminal'
    a.get_runner.return_value.start.assert_called_once()
    adapter.execute_step.assert_not_called()


def test_terminal_plan_does_not_replace_existing_plan_or_allow_remote_start(tmp_path):
    c,a,adapter=client(tmp_path);a.pending=dict(id='existing')
    assert c.post('/plate-transfer/plan',json=dict(destination='Squid',roundtrip=False)).status_code!=200
    assert a.pending==dict(id='existing')
    assert c.post('/plate-transfer/start',json=dict(plan_id='a'*32,ready=True),
                  environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code==403
    adapter.preview.assert_not_called()


def test_terminal_stop_never_stops_another_run(tmp_path):
    c,a,_=client(tmp_path);runner=a.get_runner.return_value
    runner._lock=threading.Lock();runner.active=True;runner.stop_event=threading.Event()
    runner.name='lacry_workflow_composition';a.run_meta={'plan_id':'a'*32}
    assert not c.post('/plate-transfer/stop',json=dict(plan_id='b'*32)).json['stop_requested']
    assert not runner.stop_event.is_set()
    assert c.post('/plate-transfer/stop',json=dict(plan_id='a'*32)).json['stop_requested']
    assert runner.stop_event.is_set()


def test_terminal_status_reads_requested_record_only(tmp_path):
    c,_,_=client(tmp_path)
    (tmp_path/('a'*32+'.json')).write_text(json.dumps(dict(status='completed_controller_verified',plate_destination='Hamilton')))
    assert c.get('/plate-transfer/status/'+'a'*32).json['plate_destination']=='Hamilton'
    assert c.get('/plate-transfer/status/'+'b'*32).status_code==404


def test_disconnected_robot_refusal_is_json_and_never_dispatches(tmp_path):
    from autonomy import TransferError
    c,a,adapter=client(tmp_path)
    adapter.preview.side_effect=TransferError('not connected — press Connect first')
    reply=c.post('/plate-transfer/plan',json=dict(destination='Squid',roundtrip=True))
    assert reply.status_code==409 and reply.is_json
    assert reply.json==dict(ok=False,code='transfer_refused',message='not connected — press Connect first')
    assert a.pending is None
    a.get_runner.return_value.start.assert_not_called()
    adapter.execute_step.assert_not_called()


def test_start_revalidation_refusal_never_dispatches(tmp_path):
    from autonomy import TransferError
    c,a,adapter=client(tmp_path)
    adapter.preview.return_value=dict(plate_id=None,slot=1,destination='Squid',roundtrip=True)
    adapter.steps.return_value=composition_outline('Cellvis P24-1.5H-N',1,'Squid',True)[0]
    reply=c.post('/plate-transfer/plan',json=dict(destination='Squid',roundtrip=True))
    ident=reply.json['plan']['id']
    adapter.verify.side_effect=TransferError('not connected — press Connect first')
    reply=c.post('/plate-transfer/start',json=dict(plan_id=ident,ready=True))
    assert reply.status_code==409 and 'not connected' in reply.json['message']
    a.get_runner.return_value.start.assert_not_called()
    assert not (tmp_path/(ident+'.json')).exists()


def test_unexpected_plan_error_is_json_and_logged(tmp_path,caplog):
    c,a,adapter=client(tmp_path)
    adapter.preview.side_effect=RuntimeError('fixture unexpected failure')
    reply=c.post('/plate-transfer/plan',json=dict(destination='Squid',roundtrip=False))
    assert reply.status_code==500 and reply.json['code']=='console_error'
    assert 'fixture unexpected failure' in caplog.text
    a.get_runner.return_value.start.assert_not_called()


@pytest.mark.parametrize('raw,expected',[
    (b'{"ok":false,"message":"not connected - press Connect first"}', 'not connected - press Connect first'),
    (b'<!doctype html><title>500 Internal Server Error</title>', 'Console HTTP 500 during plan.')])
def test_cli_reports_readable_http_errors_without_html(monkeypatch,raw,expected):
    error=HTTPError(cli.BASE+'/plan',500,'Server error',{},io.BytesIO(raw))
    monkeypatch.setattr(cli,'urlopen',Mock(side_effect=error))
    with pytest.raises(cli.ApiRejected) as caught:cli.api('plan',dict(destination='Squid',roundtrip=True))
    assert expected in str(caught.value) and '<!doctype' not in str(caught.value)


def test_console_hook_keeps_cancel_available_and_preserves_workflow_evidence():
    # Exercise the actual hook without importing app.py's live device owners.
    from flask import request
    tree=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text(encoding='utf-8'))
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='command_ownership')
    fn.decorator_list=[]
    lock=threading.RLock();runner=Mock(active=True,reserved=False)
    scope=dict(request=request,jsonify=jsonify,_dispatch_lock=lock,runner=runner)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),scope)
    app=Flask(__name__)
    with app.test_request_context('/researcher/api/plate-transfer/stop',method='POST'):
        assert scope['command_ownership']() is None
        assert 'bioyond.dispatch_locked' not in request.environ
    for action in ('plan','start'):
        with app.test_request_context('/researcher/api/plate-transfer/'+action,method='POST'):
            assert scope['command_ownership']()[1]==409
            lock.release()
        runner.active=False
        with app.test_request_context('/researcher/api/plate-transfer/'+action,method='POST'):
            assert scope['command_ownership']() is None
            assert request.environ['bioyond.dispatch_locked']
            lock.release()
        runner.active=True


@pytest.mark.parametrize('destination',['Squid','Hamilton'])
@pytest.mark.parametrize('roundtrip',[False,True])
def test_station_executor_uses_verified_registration_and_correct_native_route(tmp_path,monkeypatch,destination,roundtrip):
    import cellvis24_workflow as workflow
    def write(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value));return path
    scan=write('scan.json',dict(result='decoded',plate_registry=dict(saved=True,plate_id='001')))
    home=write('home.json',dict(status='completed'))
    receipt=write('registration.json',dict(status='registered_HOME_released',plate_id='001',
        home_receipt=str(home),home_sha256=registration.sha(home),scan_receipt=str(scan),
        scan_sha256=registration.sha(scan),finished_at=time.time()))
    prior=dict(record=str(receipt),plate_id='001',home_receipt=str(home))
    plan=Mock(return_value=dict(id='a'*32));execute=Mock(return_value=dict(ok=True,record='native'))
    monkeypatch.setattr(workflow,'plan',plan);monkeypatch.setattr(workflow,'execute_checked_steps',execute)
    monkeypatch.setattr(workflow,'validate_steps',Mock());monkeypatch.setattr(registration,'preflight',Mock())
    steps=registration.delivery_steps(destination,roundtrip)
    result=registration.deliver(Mock(),Mock(),prior,steps,destination,roundtrip)
    assert plan.call_args.args[2:]==([destination.lower()],1)
    assert plan.call_args.kwargs.get('recorded_hamilton_variant')==('opposite3' if destination=='Hamilton' else None)
    assert execute.call_args.args[3]['steps']==steps
    assert execute.call_args.kwargs['receipt_status']==('completed' if roundtrip else 'experiment_delivery_complete')
    assert result['plate_location']==('HOME' if roundtrip else destination)
    # Cross-destination substitution cannot be approved, even with a valid receipt.
    with pytest.raises(Exception,match='changed after approval'):
        registration.deliver(Mock(),Mock(),prior,steps,'Hamilton' if destination=='Squid' else 'Squid',roundtrip)
    write('scan.json',dict(result='no_read'))
    with pytest.raises(Exception,match='matching barcode'):
        registration.deliver(Mock(),Mock(),prior,steps,destination,roundtrip)
    execute.assert_called_once()


@pytest.mark.parametrize('destination',['Squid','Hamilton'])
@pytest.mark.parametrize('roundtrip',[False,True])
def test_live_adapter_preview_and_dispatch_preserve_destination(monkeypatch,destination,roundtrip):
    import hotel_squid_composition as adapter_module
    import cellvis24_workflow as workflow
    import home_hamilton_exchange as exchange
    _,_,geometry=adapter_module.hotel(1)
    a=Mock();backend=a.backend
    backend.params.return_value=geometry['cfg'];backend.s.envelope=geometry['envelope']
    state=dict(pose_mm=geometry['home'],joints=dict(J1=100,J2=1,J3=2,J4=3))
    monkeypatch.setattr(adapter_module,'preflight',lambda service:state)
    monkeypatch.setattr(exchange,'native',lambda service:dict(moving=False,external_axes=dict(E1=28,E2=1.77)))
    squid=Mock();hamilton=Mock()
    monkeypatch.setattr(workflow,'squid_ready',squid);monkeypatch.setattr(workflow,'hamilton_ready',hamilton)
    adapter=HotelSquidAdapter(a)
    spec=adapter.preview(None,1,destination,'Cellvis P24-1.5H-N',roundtrip)
    adapter.verify(spec)
    (hamilton if destination=='Hamilton' else squid).assert_called()
    (squid if destination=='Hamilton' else hamilton).assert_not_called()
    deliver=Mock(return_value=dict(ok=True));monkeypatch.setattr(registration,'deliver',deliver)
    last=adapter.steps(spec)[-1]['id'];prior={'record':'registered'}
    adapter.execute_step(Mock(),spec,last,prior)
    assert deliver.call_args.args[2:]==(prior,spec['continuation']['delivery_steps'],destination,roundtrip)
    backend.s.move_gripper.assert_not_called();backend.s.move_cartesian.assert_not_called()
