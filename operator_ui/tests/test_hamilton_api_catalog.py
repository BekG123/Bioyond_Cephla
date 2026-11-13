"""Offline contract/approval tests; no hardware HTTP or SDK connections."""
from copy import deepcopy
import json
import time
import sys
from pathlib import Path
from unittest.mock import Mock
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hamilton_api_catalog import HamiltonCatalog
from lacry_agent import TOOLS
from lacry_hamilton_api import HamiltonAPI
from researcher_teaching import TeachingError
from test_dilution_authoring import system, spec, LABWARE, approved
from dilution_protocol import compile_spec


def test_entire_native_catalog_and_unique_method_path_keys():
    catalog=HamiltonCatalog()
    assert len(catalog.operations)==318
    found=[];offset=0
    while True:
        page=catalog.search(offset=offset,limit=50)
        found.extend(x['operation'] for x in page['operations'])
        if page['next_offset'] is None:break
        offset=page['next_offset']
    assert len(set(found))==318
    assert catalog.search(query='thermal temperature')['matched']>=2
    assert catalog.detail('POST /api/v1/protocol-run/create')['schemas']
    names={t['name'] for t in TOOLS}
    assert {'get_hamilton_api_catalog','get_hamilton_api_operation','read_hamilton_api','plan_hamilton_api_request','adopt_hamilton_protocol'}<=names


@pytest.mark.parametrize('key',[
    'GET /api/v1/users/disable-user-management','GET /api/v1/protocols/validate/{protocolId}',
    'GET /api/v1/protocol-verification/{id}','GET /api/v1/credentials',
    'POST /api/v1/verification/signature','POST /api/v1/calibration/channel-results'])
def test_effectful_or_private_operations_are_not_reads(key):
    assert HamiltonCatalog().policy(key)!='read'


@pytest.mark.parametrize('value',['../credentials','7?x=1','%2f','7/2','7\\2',True,0.5])
def test_typed_ids_and_path_injection_fail(value):
    with pytest.raises(TeachingError):HamiltonCatalog().request('GET /api/v1/protocols/{id}',path_parameters={'id':value})


def test_unknown_url_parameter_and_body_rejected():
    cat=HamiltonCatalog()
    for args in [dict(operation='GET http://evil.invalid'),
            dict(operation='GET /api/v1/protocols',query={'url':'http://evil.invalid'}),
            dict(operation='GET /api/v1/protocols',body={})]:
        with pytest.raises(TeachingError):cat.request(**args)
    with pytest.raises(TeachingError):cat.request('POST /api/v1/protocol-run/create',body={'ProtocolId':'not-an-int'})


def test_read_and_propose_do_not_write(system):
    fake,agent,runner=system;api=agent.hamilton_api
    assert api.read('GET /api/v1/protocols')['result']==[]
    assert not fake.writes()
    api.propose('POST /api/v1/protocols',purpose='Create an empty protocol draft',body={'Name':'test','Deck':{'Positions':[]}})
    assert not fake.writes()
    assert agent.pending['protocol_review']['request']['body']['Name']=='test'


@pytest.mark.parametrize('key', ['POST /api/v1/protocol-run/create','PUT /api/v1/protocol-run/load-complete',
    'POST /api/v1/verification/signature','GET /api/v1/credentials','PUT /api/v1/protocols/import'])
def test_raw_api_cannot_bypass_lifecycle_or_human_identity(system,key):
    fake,agent,_=system
    agent.pending={'id':'unrelated-old-plan'}
    with pytest.raises(TeachingError):agent.hamilton_api.propose(key,purpose='attempt bypass',body={})
    assert not fake.writes()
    assert agent.pending is None


def candidate(system):
    _,agent,_=system
    agent.hamilton_api.propose('GET /api/v1/protocols/validate/{protocolId}',purpose='Validate saved protocol',path_parameters={'protocolId':101})
    return deepcopy(agent.pending)


def test_human_confirmation_is_required_and_single_use(system):
    fake,agent,runner=system;plan=candidate(system)
    with pytest.raises(TeachingError,match='person'):agent.hamilton_api.start(plan)
    fake.protocol={'name':'fixture'}
    agent.confirm_from_chat('Yes');runner._thread.join(5)
    assert agent.run_state['ok'] is True
    assert len([c for c in fake.calls if c[1]=='protocols/validate/101'])==1
    plan['confirmation_source']='researcher_chat'
    with pytest.raises(TeachingError):agent.hamilton_api.start(plan)


@pytest.mark.parametrize('change',[
    lambda p:p['request'].update(path='instruments/initialize'),
    lambda p:p.update(at=time.time()-601),
    lambda p:p.update(session_id='other-session'),
    lambda p:p.update(schema_hash='changed'),
    lambda p:p['arguments']['path_parameters'].update(protocolId=102)])
def test_approval_binding(system,change):
    fake,agent,_=system;plan=candidate(system);plan['confirmation_source']='researcher_chat';change(plan)
    with pytest.raises(TeachingError):agent.hamilton_api.start(plan)
    assert not any(c[1]=='protocols/validate/101' for c in fake.calls)


def test_timeout_unknown_no_redispatch(system):
    fake,agent,runner=system;candidate(system);fake.fail_path='protocols/validate/101'
    agent.confirm_from_chat('Yes');runner._thread.join(5)
    assert agent.run_state['ok'] is False
    marker=json.loads((fake.h.folder/'active.json').read_text())
    assert marker['status']=='failed_or_uncertain'
    assert len([c for c in fake.calls if c[1]==fake.fail_path])==1


def test_async_ack_not_physical_completion(system):
    fake,agent,runner=system
    agent.hamilton_workflow=Mock(return_value=Mock())
    fake.h.request=Mock(return_value={'ok':True})
    agent.hamilton_api.propose('POST /api/v1/instruments/initialize',purpose='Initialize Hamilton')
    agent.confirm_from_chat('Yes');runner._thread.join(5)
    assert not agent.run_state['ok']
    marker=json.loads((fake.h.folder/'active.json').read_text())
    assert marker['status']=='finished_unverified'
    assert fake.h.request.call_count==1


def addition_spec():
    value=spec();value.pop('dilutions');value['tip_wells']=['A1']
    value['initial_volumes']=[dict(site=2,well='A1',contents='Water',volume_ul=500,minimum_remaining_ul=100),
        dict(site=4,well='A5',contents='Existing culture',volume_ul=200,minimum_remaining_ul=0)]
    value['additions']=[dict(source=dict(site=2,well='A1'),destination=dict(site=4,well='A5'),volume_ul=10,mix_after=False)]
    return value


def test_additions_into_occupied_wells_use_same_native_compiler():
    c=compile_spec(addition_spec(),LABWARE)
    assert c['tips_required']==1
    assert c['summary'][0]['initial_volume_ul']==200
    assert c['summary'][0]['final_volume_ul']==210
    assert c['steps'][0]['newTipsEachTransfer'] is True
    assert c['steps'][0]['mixAfterDispense'] is False


@pytest.mark.parametrize('change',[
    lambda s:s['initial_volumes'][0].update(volume_ul=105),
    lambda s:s['initial_volumes'][1].update(volume_ul=99999),
    lambda s:s['additions'][0].update(volume_ul=0.1),
    lambda s:s['additions'][0].update(volume_ul=10.01),
    lambda s:s['additions'][0].update(mix_after='false'),
    lambda s:s['additions'][0]['destination'].update(well='E5'),
    lambda s:s.update(dilutions=[]),
    lambda s:s['tip_wells'].append('A2')])
def test_invalid_additions_fail(change):
    value=addition_spec();change(value)
    with pytest.raises(TeachingError):compile_spec(value,LABWARE)


def test_addition_create_simulate_commission_all_faked(system):
    fake,agent,_=system
    identity=agent.protocol_authoring.draft(addition_spec())['draft_id']
    fake.compiled=agent.protocol_authoring.read(identity)['compiled']
    assert approved(system,identity,'create')['status']=='created'
    assert approved(system,identity,'simulate')['status']=='simulated'
    assert approved(system,identity,'commission','add-water')['status']=='commissioned'
    assert fake.h.settings()['recipes']['add-water']['protocol_id']==101


def test_adopt_existing_native_protocol_without_native_writes(system):
    fake,agent,_=system
    identity=agent.protocol_authoring.draft(addition_spec())['draft_id']
    fake.compiled=agent.protocol_authoring.read(identity)['compiled']
    record=approved(system,identity,'create');fake.calls.clear()
    adopted=agent.protocol_authoring.adopt(101,record['spec'])
    assert adopted['status']=='created'
    assert not fake.writes()
    assert adopted['protocol_hash']==record['protocol_hash']
