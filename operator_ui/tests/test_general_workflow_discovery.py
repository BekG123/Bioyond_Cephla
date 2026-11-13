"""Discovery coverage and contract-driven execution; every physical boundary is fake."""
from copy import deepcopy
import json
import threading
from pathlib import Path
from unittest.mock import Mock
import pytest

import composed_instrument_chain as chain
from workflow_capabilities import compose_hotel,compose_ordered,load
from workflow_discovery import discover
from lacry_workflow_router import WorkflowRouter,catalog
from test_composed_instrument_chain import setup,harness
from test_hamilton_simulate_execute import experiment,starts
from test_dilution_authoring import system

PROFILE=chain.PROFILE
OPS=['retrieve_hotel','register_plate','deliver_hamilton','hamilton_protocol']


def request(ops,**inputs):
    c=compose_hotel(ops,PROFILE,1)
    stations=list(dict.fromkeys(x['capability']['station'] for x in c['capabilities'] if 'station' in x['capability']))
    return dict(operations=ops,composition=c,stations=stations,**inputs)


def test_discovery_covers_every_installed_tool_and_native_facade():
    from lacry_agent import TOOLS
    a=Mock();a.lab_api.tools.return_value=[dict(name='future_planner',description='Newly installed planner',input_schema=dict(type='object',properties=dict(value=dict(type='string')),required=['value']))]
    index=catalog(a)
    assert {t['name'] for t in index['workflows']}=={t['name'] for t in TOOLS}|{'future_planner'}
    assert catalog(a,workflow='future_planner')['input_schema']['required']==['value']
    assert catalog(workflow='plan_hamilton_experiment')['input_schema']['properties']['draft_id']


def test_leave_at_station_and_explicit_return_are_distinct():
    c=compose_hotel(OPS,PROFILE,1)
    assert c['final']['plate_location']=='Hamilton'
    assert [x['capability']['operation'] for x in c['capabilities']]==OPS
    c=compose_hotel(OPS+['return_HOME'],PROFILE,1)
    assert c['final']['plate_location']=='HOME'
    assert c['capabilities'][-1]['capability']['operation']=='retrieve_hamilton'


def test_reverse_station_order_is_composed_without_new_cases():
    ops=['retrieve_hotel','squid_image','hamilton_protocol','return_HOME']
    c=compose_hotel(ops,PROFILE,1)
    expanded=[x['capability']['operation'] for x in c['capabilities']]
    assert expanded==['retrieve_hotel','register_plate','deliver_squid','squid_image','retrieve_squid','deliver_hamilton','hamilton_protocol','retrieve_hamilton']
    assert c['requested_operations']==ops and c['final']['plate_location']=='HOME'


def test_existing_plate_uses_same_contracts_without_fresh_registration():
    c=compose_ordered(['hamilton_protocol','squid_image'],dict(plate_location='Hamilton',payload='empty',arm_location='HOME',registered=True),PROFILE)
    assert [x['capability']['operation'] for x in c['capabilities']]==['hamilton_protocol','retrieve_hamilton','deliver_squid','squid_image']
    assert c['final']['plate_location']=='Squid'


@pytest.mark.parametrize('ops,profile,slot',[
    (OPS+['arm_full_calibration'],PROFILE,1),
    (OPS,'48_well_projected_20261026',1),
    (OPS,PROFILE,2),
    (['retrieve_hotel','retrieve_hamilton'],PROFILE,1),
    (['retrieve_hotel','register_plate','register_plate'],PROFILE,1)])
def test_unbound_boundaries_never_return_a_prefix(ops,profile,slot):
    with pytest.raises(Exception):compose_hotel(ops,profile,slot)


def test_router_preserves_exact_request_on_missing_input():
    a=Mock();a.lock=threading.RLock();a._plan_view.side_effect=deepcopy
    from autonomy import TransferError
    a.workflow_composition.propose.side_effect=TransferError('hamilton_protocol requires draft_id or recipe')
    result=WorkflowRouter(a).propose(OPS,plate_profile=PROFILE,source_slot=1)
    assert result['blocked'] and a.pending['labels']==OPS
    assert 'draft_id' in a.pending['blockers'][0]
    assert 'composition' in a.workflow_composition.propose.call_args.kwargs['instrument_request']
    a.confirm.assert_not_called()


def test_existing_48well_planner_is_not_shadowed_by_cellvis_contracts():
    a=Mock();a.lock=threading.RLock();a._plan_view.side_effect=deepcopy
    a.automatic_workflow.return_value.propose.return_value=dict(executable=True)
    result=WorkflowRouter(a).propose(['deliver_squid','squid_image','retrieve_squid'],
        plate_profile='48_well_projected_20261026')
    assert result['awaiting_confirmation']
    a.automatic_workflow.return_value.propose.assert_called_once()


def test_exact_requested_hotel_chain_stops_at_hamilton(tmp_path,monkeypatch):
    adapter,run,spec,prior,history,squid=harness(tmp_path,monkeypatch,('Hamilton',))
    spec['instrument_chain']=chain.prepare(adapter.backend,request(OPS,recipe='reviewed'))
    for step in chain.steps(spec['instrument_chain']):prior=adapter.execute_step(run,spec,step['id'],prior)
    assert history==[('Hamilton','delivery')]
    assert prior['plate_location']=='Hamilton'
    assert adapter.backend.instrument.start.call_count==1


def test_reverse_order_dispatches_each_exact_job_and_returns(tmp_path,monkeypatch):
    adapter,run,spec,prior,history,squid=harness(tmp_path,monkeypatch)
    ops=['retrieve_hotel','squid_image','hamilton_protocol','return_HOME']
    spec['instrument_chain']=chain.prepare(adapter.backend,request(ops,recipe='reviewed'))
    for step in chain.steps(spec['instrument_chain']):prior=adapter.execute_step(run,spec,step['id'],prior)
    assert history==[('Squid','delivery'),('Squid','retrieval'),('Hamilton','delivery'),('Hamilton','retrieval')]
    assert prior['plate_location']=='HOME'
    assert squid.start.call_count==adapter.backend.instrument.start.call_count==1


def test_repeated_handling_has_unique_receipt_claims(monkeypatch):
    backend,_,_=setup(monkeypatch,('Hamilton',))
    ops=OPS+['retrieve_hamilton','deliver_hamilton','retrieve_hamilton']
    p=chain.prepare(backend,request(ops,recipe='reviewed'))
    ids=[s['id'] for s in chain.steps(p)]
    assert len(ids)==len(set(ids))==5


def test_composed_draft_binding_is_read_only_and_rejects_changes(experiment):
    fake,a,_,identity=experiment
    p=chain.prepare(a.backend,request(OPS,draft_id=identity),a)
    assert not fake.writes() and p['final_location']=='Hamilton'
    assert p['hamilton']['protocol_review']['physical_execution_authorized']
    record=a.protocol_authoring.read(identity);record['attempts'].append({'changed':True});a.protocol_authoring.save(record)
    with pytest.raises(Exception,match='changed'):chain.verify(a.backend,p,agent=a)
    assert not fake.writes()


def test_unparked_hamilton_blocks_transport_during_planning(experiment):
    fake,a,_,identity=experiment
    status=fake.h.status
    fake.h.status=lambda fresh=False:dict(status(fresh),parked=False)
    with pytest.raises(Exception,match='parked'):
        chain.prepare(a.backend,request(OPS,draft_id=identity),a)
    assert not fake.writes()


@pytest.mark.parametrize('fail_simulation',[False,True])
def test_composed_draft_uses_outer_checkpoint_and_one_conditional_live_run(experiment,fail_simulation):
    fake,a,_,identity=experiment
    p=a.hamilton_experiment.prepare_bound(identity)
    p.update(id='outer-plan',plate_id='FRESHLY-SCANNED',confirmation_source='researcher_button')
    run=Mock();run.stopped.return_value=False
    checkpoint=Mock();fake.unknown=fail_simulation
    if fail_simulation:
        with pytest.raises(Exception):a.hamilton_experiment.execute(run,p,checkpoint=checkpoint,composed=True)
        assert [b['simulate'] for b in starts(fake)]==[True]
    else:
        result=a.hamilton_experiment.execute(run,p,checkpoint=checkpoint,composed=True)
        assert result['physical_ticket']['plate_id']=='FRESHLY-SCANNED'
        assert [b['simulate'] for b in starts(fake)]==[True,False]
    assert checkpoint.called
    assert a.hamilton_experiment.arm_checkpoint.call_count==0


@pytest.fixture
def custody():
    from test_workflow_capabilities import AdapterTests
    case=AdapterTests();case.setUp()
    try:yield case
    finally:case.doCleanups()


def test_registered_plate_adapter_runs_job_from_custody_without_hotel_or_scan(custody,monkeypatch):
    from composed_operations import RegisteredPlateAdapter
    c=custody
    _,squid,_=setup(monkeypatch,('Squid',))
    adapter=RegisteredPlateAdapter(backend=c.backend,registry=c.registry,folder=c.folder)
    spec=adapter.preview_operations(['squid_image','return_HOME'],image_count=5)
    adapter.verify(spec)
    assert spec['plate_id']=='P1'
    assert [s['action'] for s in adapter.steps(spec)]==['run','retrieve']
    monkeypatch.setattr(chain,'at_home',lambda b,c:None)
    def start(plan,folder,save,stopped):
        ticket=dict(status='started',experiment_id='new-squid');save(ticket);return ticket
    def wait(plan,ticket,save,stopped,progress):
        ticket['status']='completed';save(ticket);return dict(ok=True)
    squid.start.side_effect=start;squid.wait.side_effect=wait
    squid.restore_loading.return_value=dict(ok=True);squid.observe.return_value=dict(completion_confirmed=True)
    history=[]
    def handling(run,backend,spec,context,group,action):
        history.append(action);context['plate_location']='HOME';return dict(ok=True)
    monkeypatch.setattr(chain,'handling',handling)
    run=Mock(run_id='registered-run');run.stopped.return_value=False
    prior=None
    for step in adapter.steps(spec):prior=adapter.execute_step(run,spec,step['id'],prior)
    assert history==['retrieval'] and prior['plate_location']=='HOME'
    c.backend.s.move_gripper.assert_not_called()


def test_completed_instrument_receipt_supplies_bound_custody(custody,monkeypatch):
    import capability_workflow as binding
    from composed_cellvis_registration import sha
    from labfacade.approval import plan_hash
    c=custody
    _,_,prepared=setup(monkeypatch,('Squid',))
    prepared['final_location']='Squid'
    prepared['request']=request(['retrieve_hotel','squid_image'])
    spec=c.outer['plan']['composition'];spec['instrument_chain']=prepared
    phase=c.folder/'phase.json'
    data=dict(status='completed',binding=plan_hash(spec),step=chain.steps(prepared)[-1]['id'],context=dict(
        plate_id='P1',plate_location='Squid',motion_record=str(c.motion_path),motion_sha256=sha(c.motion_path),motion=c.motion['plan']))
    phase.write_text(json.dumps(data))
    c.outer['steps'][-1]['result']=dict(record=str(phase),sha256=sha(phase),plate_id='P1',plate_location='Squid')
    c.outer_path.write_text(json.dumps(c.outer))
    source,motion=binding.checkpoint(c.folder)
    assert source['state']['plate_location']=='Squid' and motion==c.motion
    phase.write_text('{}')
    with pytest.raises(Exception,match='custody'):binding.checkpoint(c.folder)


def test_nomix_needs_no_invented_mixing_parameters():
    from test_hamilton_api_catalog import addition_spec
    from test_dilution_authoring import LABWARE
    from dilution_protocol import compile_spec
    s=addition_spec()
    for addition in s['additions']:addition['mix_after']=False
    s['pipetting']=dict(aspirate_height_mm=2,dispense_height_mm=2)
    compiled=compile_spec(s,LABWARE)
    for step in compiled['steps']:
        assert step['mixAfterDispense'] is False and step['dispenseSettings']['mixCycles']==0
        assert step['aspirateSettings']['pipettingHeightStartPoint']=='FromContainerBottom'
    s['additions'][0]['mix_after']=True
    with pytest.raises(Exception,match='Pipetting'):compile_spec(s,LABWARE)
