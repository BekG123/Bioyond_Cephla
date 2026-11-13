"""Readback resolves validation only; writes, execution, and Stop are not retried."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from test_hamilton_simulate_execute import experiment,propose,approve,starts
from test_dilution_authoring import system
from researcher_teaching import TeachingError


def test_validation_timeout_reads_back_then_simulates_and_runs_once(experiment):
    fake,agent,runner,identity=experiment
    fake.fail_path='protocols/validate/101'
    propose(experiment);record=approve(experiment)
    assert record['status']=='experiment_completed',record.get('error')
    assert record['validation_phase']['status']=='reconciled'
    assert [b['simulate'] for b in starts(fake)]==[True,False]
    assert sum(path=='protocols/validate/101' for _,path,_ in fake.calls)==1
    assert sum(method=='POST' and path=='protocols' for method,path,_ in fake.calls)==1
    assert sum(method=='POST' and path=='protocols/101/step' for method,path,_ in fake.calls)==len(record['compiled']['steps'])
    assert not (fake.h.folder/'active.json').exists()


@pytest.mark.parametrize('change',['changed_steps','invalid','running','stop','catalog'])
def test_uncertain_or_changed_validation_never_advances(experiment,change):
    fake,agent,runner,identity=experiment;propose(experiment)
    original=fake.h.request
    def request(method,path,body=None):
        if path=='protocols/validate/101':
            if change=='changed_steps':fake.protocol['steps'][0]['aspirateSettings']['transferVolume']=999
            if change=='invalid':fake.protocol['validationErrors']=['Rejected by Hamilton']
            if change=='running':fake.running=True
            if change=='stop':runner.request_stop()
            if change=='catalog':agent.protocol_authoring.verify_catalog=Mock(side_effect=TeachingError('Catalog changed'))
            fake.calls.append((method,path,body));raise TimeoutError('timed out')
        return original(method,path,body)
    fake.h.request=request
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert starts(fake)==[]
    assert sum(path=='protocols/validate/101' for _,path,_ in fake.calls)==1


def test_readback_polling_is_bounded_and_never_resends_validation(experiment):
    fake,agent,runner,identity=experiment;propose(experiment)
    original=fake.h.request
    def request(method,path,body=None):
        if path=='protocols/validate/101':
            fake.protocol['isValid']=False;fake.calls.append((method,path,body));raise TimeoutError('timed out')
        return original(method,path,body)
    fake.h.request=request
    agent.protocol_authoring.clock=Mock(side_effect=[0,46])
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert starts(fake)==[]


def test_http_validation_has_operation_timeout_but_reads_stay_short(tmp_path):
    from hamilton_prep import HamiltonPrep
    from unittest.mock import MagicMock
    cfg=tmp_path/'config.json';cfg.write_text(json.dumps(dict(base_url='http://192.168.100.101/NimbusLite/api/v1')))
    h=HamiltonPrep(config=cfg,folder=tmp_path/'owned')
    response=MagicMock();response.__enter__.return_value.read.return_value=b'{}'
    h.opener=Mock();h.opener.open.return_value=response
    h.call('GET','protocols/validate/17');assert h.opener.open.call_args.kwargs['timeout']==90
    h.call('GET','protocols/17');assert h.opener.open.call_args.kwargs['timeout']==5
    h.call('POST','protocol-run/create',{});assert h.opener.open.call_args.kwargs['timeout']==30


@pytest.fixture
def stopped_creation(experiment,tmp_path,monkeypatch):
    from test_workflow_capabilities import AdapterTests
    from test_general_workflow_discovery import request,OPS
    from composed_instrument_chain import prepare
    from composed_cellvis_registration import sha
    from labfacade.approval import plan_hash
    from plate_registry import PlateRegistry
    import cellvis24_workflow
    fake,a,_,identity=experiment
    c=AdapterTests();c.setUp()
    try:
        a.workflow_composition.folder=c.folder
        registry=PlateRegistry(tmp_path/'plates.sqlite3')
        with registry.db() as db:db.execute("INSERT INTO plates(plate_id,first_seen,last_seen) VALUES ('P1','test','test')")
        a.workflow_composition.adapter._registry=registry
        prepared=prepare(a.backend,request(OPS,draft_id=identity),a)
        record=a.protocol_authoring.read(identity)
        record.update(plate_id='P1',experiment_plan_id='old-run')
        fake.fail_path='protocols/validate/101'
        monkeypatch.setattr(a.protocol_authoring,'validated_readback',Mock(side_effect=TimeoutError('old unrecovered timeout')))
        with pytest.raises(Exception):
            with fake.h.owned('experiment_simulation') as ticket:a.protocol_authoring.create(record,ticket,lambda:None)
        record.update(status='failed_or_uncertain',error='Hamilton request outcome is uncertain; no retry was sent. timed out')
        a.protocol_authoring.save(record)
        monkeypatch.undo();fake.fail_path=None
        # Reapply only this fixture's runtime read-only boundaries.
        monkeypatch.setattr(cellvis24_workflow,'RUNS',c.runs)
        monkeypatch.setattr('composed_instrument_chain.at_home',lambda backend,context:None)
        outbound=prepared['groups'][0]['delivery']
        c.motion['plan']['steps']=outbound;c.motion['steps']=[dict(s,status='completed') for s in outbound]
        c.motion_path.write_text(json.dumps(c.motion))
        spec=dict(plate_profile='Cellvis P24-1.5H-N',instrument_chain=prepared)
        context=dict(plate_id='P1',plate_location='Hamilton',motion_record=str(c.motion_path),motion_sha256=sha(c.motion_path),motion=c.motion['plan'])
        receipt=c.folder/'delivery.json'
        receipt.write_text(json.dumps(dict(status='completed',binding=plan_hash(spec),step='instrument_hamilton_deliver',run_id='old-run',context=context)))
        prior=dict(record=str(receipt),sha256=sha(receipt),plate_id='P1',plate_location='Hamilton')
        outer=dict(status='stopped_or_uncertain',finished_at=1,error='timed out',plan=dict(composition=spec),
            steps=[dict(step='instrument_hamilton_deliver',status='completed',result=prior),dict(step='instrument_hamilton_run',status='dispatching')])
        c.outer_path.write_text(json.dumps(outer));(c.folder/'unresolved.json').write_text(json.dumps(dict(record=str(c.outer_path))))
        yield fake,a,identity,c
    finally:c.doCleanups()


def test_stopped_validation_reconciles_only_local_holds_and_custody(stopped_creation):
    from hamilton_validation_recovery import reconcile
    from capability_workflow import checkpoint
    fake,a,identity,c=stopped_creation;before=deepcopy(fake.writes())
    result=reconcile(a,c.outer_path.stem)
    assert result['reconciled'] and result['hardware_started'] is False
    assert result['remaining_operations']==['hamilton_protocol']
    assert fake.writes()==before and starts(fake)==[]
    assert not (c.folder/'unresolved.json').exists() and not (fake.h.folder/'active.json').exists()
    assert a.protocol_authoring.read(identity)['status']=='created'
    source,motion=checkpoint(c.folder)
    assert source['state']['plate_location']=='Hamilton' and source['plate_id']=='P1'
    assert json.loads(c.outer_path.read_text())['status']=='reconciled_before_instrument_run'


@pytest.mark.parametrize('change',['run_request','protocol','arm','review','later_motion'])
def test_stopped_recovery_refuses_unproven_boundaries(stopped_creation,monkeypatch,change):
    from hamilton_validation_recovery import reconcile
    fake,a,identity,c=stopped_creation
    if change=='run_request':
        marker=json.loads((fake.h.folder/'active.json').read_text());journal=fake.h.folder/(marker['request_id']+'.jsonl')
        with journal.open('a') as stream:stream.write(json.dumps(dict(kind='request',data=dict(method='POST',path='protocol-run/create',body={})))+'\n')
    elif change=='protocol':fake.protocol['steps'][0]['name']='changed'
    elif change=='arm':monkeypatch.setattr('composed_instrument_chain.at_home',Mock(side_effect=TeachingError('Arm moved')))
    elif change=='review':
        record=a.protocol_authoring.read(identity);record['compiled']['summary'][0]['added_volume_ul']=99;a.protocol_authoring.save(record)
    else:
        other=c.runs/'later'/'run.json';other.parent.mkdir();other.write_text('{}')
    before=deepcopy(fake.writes())
    with pytest.raises(Exception):reconcile(a,c.outer_path.stem)
    assert (c.folder/'unresolved.json').exists() and (fake.h.folder/'active.json').exists()
    assert fake.writes()==before
