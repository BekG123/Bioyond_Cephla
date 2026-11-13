"""Offline authoring/approval lifecycle. All Hamilton writes go to an in-memory fake."""
from copy import deepcopy
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import time
from unittest.mock import Mock

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dilution_protocol import compile_spec, normalized, verify_protocol, verify_simulation
from hamilton_prep import HamiltonPrep, digest
from lacry_agent import LacryAgent, TOOLS
from lacry_protocol_authoring import ProtocolAuthoring
from researcher_teaching import TeachingError
from sequences import Runner

FIXTURES=Path(__file__).parent/'fixtures/dilution'
NATIVE=json.loads((FIXTURES/'native_catalog.json').read_text())
LABWARE={int(k):v for k,v in NATIVE['labware'].items()}
HISTORICAL=json.loads((FIXTURES/'historical_result.json').read_text())


def spec():
    return dict(name='Example independent dilutions',plate_profile='Cellvis P24-1.5H-N',transported_plate_site=4,
        deck=[dict(site=2,labware_id=128),dict(site=4,labware_id=128),dict(site=7,labware_id=8)],
        tip_site=7,tip_wells=['A1','A2','A3','A4'],
        initial_volumes=[dict(site=4,well='A5',contents='Example stock',volume_ul=500,minimum_remaining_ul=100),
            dict(site=2,well='A1',contents='Example compatible medium',volume_ul=1000,minimum_remaining_ul=100),
            dict(site=4,well='A1',contents='empty',volume_ul=0,minimum_remaining_ul=0),
            dict(site=4,well='A2',contents='empty',volume_ul=0,minimum_remaining_ul=0)],
        dilutions=[dict(source=dict(site=4,well='A5'),diluent=dict(site=2,well='A1'),destination=dict(site=4,well='A1'),dilution_factor=2,final_volume_ul=200),
            dict(source=dict(site=4,well='A5'),diluent=dict(site=2,well='A1'),destination=dict(site=4,well='A2'),dilution_factor=4,final_volume_ul=200)],
        pipetting=dict(aspirate_height_mm=1,dispense_height_mm=2,mix_volume_ul=100,mix_cycles=3,mix_speed=20,mix_height_mm=1))


def result_for(protocol,compiled):
    # Native report structure from a real successful simulation; values below
    # are deliberately fake for this draft, not physical acceptance evidence.
    result=deepcopy(HISTORICAL)
    result.update(id='new-job',protocolName=protocol['name'],deviceSerialNumber='Simulation',runResult='Completed',errorMessages=[])
    result['runtimeSteps']=[];result['stepOverviews']=[]
    for i,t in enumerate(compiled['transfers'],1):
        step=deepcopy(HISTORICAL['runtimeSteps'][0]);step['stepNumber']=i
        activity=deepcopy(step['pipetteActivities'][0])
        for key,which in (('source','source'),('target','destination')):
            item=deepcopy(activity[key][0]);item.update(deckPosition=t[which]['site'],well=t[which]['well'],volume=str(t['volume_ul']))
            activity[key]=[item]
        step['pipetteActivities']=[activity];result['runtimeSteps'].append(step)
        result['stepOverviews'].append(deepcopy(HISTORICAL['stepOverviews'][0]))
    return result


class FakeHamilton:
    def __init__(self,tmp_path):
        self.config=tmp_path/'hamilton.json'
        self.config.write_text(json.dumps(dict(base_url='http://192.168.100.101/NimbusLite/api/v1',serial_number='fixture',recipes={})))
        self.h=HamiltonPrep(config=self.config,folder=tmp_path/'owned',request=self.request,sleep=lambda _:None)
        self.h.preflight=Mock(return_value={'connected':True})
        self.h.events=lambda _:nullcontext(Mock())
        self.h.consume=Mock();self.h.guard_errors=Mock()
        self.calls=[];self.protocol=None;self.running=False;self.loaded=False;self.job='new-job'
        self.fail_path=None;self.unknown=False;self.non_simulation=False;self.compiled=None

    def request(self,method,path,body=None):
        self.calls.append((method,path,deepcopy(body)))
        if path==self.fail_path:raise TimeoutError('injected uncertain response')
        if method=='GET' and path.startswith('labware/'):
            return deepcopy(LABWARE[int(path.split('/')[-1])])
        if path=='protocols' and method=='GET':
            return [] if self.protocol is None else [dict(id=101,name=self.protocol['name'])]
        if path=='protocols' and method=='POST':
            self.protocol=deepcopy(body);self.protocol.update(id=101,isValid=True,steps=[])
            for pos in self.protocol['deck']['positions']:
                group=pos['labwareGroup']
                if group:group.update(id=pos['position']+100,labware=deepcopy(LABWARE[group.pop('labwareId')]))
            return dict(isValid=True,validationErrors=[])
        if path=='protocols/101/step' and method=='POST':
            self.protocol['steps'].append(deepcopy(body));return dict(isValid=True)
        if path=='protocols/validate/101':return dict(isValid=True)
        if path=='protocols/101':return deepcopy(self.protocol)
        if path=='errors?offset=0&limit=30':return dict(items=[])
        if path=='protocol-run/create':self.running=True;return dict(ok=True)
        if path=='protocol-run/load-complete':self.loaded=True;return dict(ok=True)
        if path=='protocol-run':
            if not self.running:return dict(runDatalId='old-job',protocolId=0,isRunInProgress=False,protocolRunState=0)
            if self.loaded and not self.unknown:return dict(runDatalId=self.job,protocolId=0,isRunInProgress=False,protocolRunState=0)
            return dict(runDatalId=self.job,protocolId=101,isRunInProgress=True,protocolRunState=25 if self.loaded else 20,isSimulation=not self.non_simulation)
        if path=='instruments/global-run-state':return 'Idle' if self.loaded and not self.unknown else 'Running'
        if path=='protocol-run/load-instructions':return [dict(deckPosition=7,count=len(self.compiled['transfers']))]
        if path.startswith('run-data/'):return result_for(self.protocol,self.compiled)
        raise AssertionError((method,path))

    def writes(self):return [c for c in self.calls if c[0]!='GET']


@pytest.fixture
def system(tmp_path):
    fake=FakeHamilton(tmp_path);backend=Mock();backend.instrument=fake.h
    runner=Runner();agent=LacryAgent(backend,Mock(),lambda:runner,client=Mock())
    agent.public=Mock(return_value={'ok':True});agent.lab_api=Mock(active=False)
    agent.protocol_authoring=ProtocolAuthoring(agent,folder=tmp_path/'drafts')
    return fake,agent,runner


def draft(system):
    fake,agent,_=system
    identity=agent.protocol_authoring.draft(spec())['draft_id']
    fake.compiled=agent.protocol_authoring.read(identity)['compiled']
    return identity


def approved(system,identity,action,recipe_name=''):
    _,agent,runner=system
    agent.protocol_authoring.propose(identity,action,recipe_name)
    agent.confirm_from_chat('Yes')
    runner._thread.join(5)
    assert not runner.active
    return agent.protocol_authoring.read(identity)


def test_exact_dilution_math_and_native_shape():
    c=compile_spec(spec(),LABWARE)
    assert [(r['sample_ul'],r['diluent_ul']) for r in c['summary']]==[(100,100),(50,150)]
    assert c['tips_required']==4
    assert [t['volume_ul'] for t in c['transfers']]==[100,100,150,50]
    for step in c['steps']:
        reference=NATIVE['protocols']['13']['steps'][0]
        assert set(normalized(step))==set(normalized(reference))
        assert set(normalized(step['aspirateSettings']))==set(normalized(reference['aspirateSettings']))
        assert step['newTipsEachTransfer'] and not step['dispenseSettings']['useOffset']
    assert c['steps'][1]['mixAfterDispense'] and not c['steps'][0]['mixAfterDispense']
    assert next(v for v in c['remaining_volumes'] if v['site']==4 and v['well']=='A5')['volume_ul']==350


@pytest.mark.parametrize('change,reason',[
    (lambda s:s['dilutions'][0]['destination'].update(well='E1'),'does not exist'),
    (lambda s:s['initial_volumes'][2].update(volume_ul=20),'explicitly empty'),
    (lambda s:s['initial_volumes'][0].update(volume_ul=120),'Insufficient liquid'),
    (lambda s:s['dilutions'][0].update(dilution_factor=3),'rounding'),
    (lambda s:s['dilutions'][0].update(final_volume_ul=1000),'1–300'),
    (lambda s:s['dilutions'][0].update(final_volume_ul=float('nan')),'outside'),
    (lambda s:s['tip_wells'].pop(),'exactly 4'),
    (lambda s:s['tip_wells'].__setitem__(1,'A1'),'distinct'),
    (lambda s:s['pipetting'].pop('mix_speed'),'Ask for missing'),
    (lambda s:s['pipetting'].update(mix_volume_ul=250),'exceeds'),
    (lambda s:s.update(approved=True),'exactly'),
    (lambda s:s.update(transported_plate_site=3),'site 4 only'),
    (lambda s:s['deck'].append(dict(site=4,labware_id=128)),'duplicate'),
])
def test_rejects_ambiguous_or_unsafe_spec(change,reason):
    value=spec();change(value)
    with pytest.raises(TeachingError,match=reason):compile_spec(value,LABWARE)


def test_tools_are_available_and_drafting_never_writes(system):
    fake,agent,_=system
    assert {'draft_protocol','get_protocol_draft','plan_protocol_authoring','get_hamilton_authoring_catalog'}<={x['name'] for x in TOOLS}
    identity=draft(system)
    text,error=agent._run_tool('get_protocol_draft',dict(draft_id=identity))
    assert not error and json.loads(text)['status']=='draft'
    agent._run_tool('plan_protocol_authoring',dict(draft_id=identity,action='create'))
    assert not fake.writes() and agent.pending['dispatch']=='protocol_authoring'
    agent.backend.execute_step.assert_not_called()


def test_separate_human_approvals_create_simulate_commission(system):
    fake,agent,_=system;identity=draft(system)
    created=approved(system,identity,'create')
    assert created['status']=='created'
    assert not any(c[1]=='protocol-run/create' for c in fake.calls)
    before=len(fake.writes());agent.send('Yes');assert len(fake.writes())==before
    simulated=approved(system,identity,'simulate')
    assert simulated['status']=='simulated' and simulated['simulation_report']['job_id']=='new-job'
    assert fake.h.settings()['recipes']=={}
    commissioned=approved(system,identity,'commission','tetrahymena_example')
    assert commissioned['status']=='commissioned'
    recipe=fake.h.settings()['recipes']['tetrahymena_example']
    assert recipe['protocol_hash']==digest(fake.protocol) and len(recipe['cycle_loads'])==1
    assert recipe['review']['source']=='researcher_chat'
    assert recipe['plate_profile']=='Cellvis P24-1.5H-N'
    assert all(body.get('simulate') is True for _,path,body in fake.writes() if path.startswith('protocol-run/'))
    assert not (fake.h.folder/'active.json').exists()
    with pytest.raises(TeachingError):agent.protocol_authoring.propose(identity,'commission','duplicate')


def test_model_tool_cannot_approve_or_dispatch(system):
    fake,agent,_=system;identity=draft(system)
    text,error=agent._run_tool('plan_protocol_authoring',dict(draft_id=identity,action='create',approved=True))
    assert error and not fake.writes()
    plan=agent.protocol_authoring.propose(identity,'create')['plan']
    with pytest.raises(TeachingError,match='Only the researcher'):agent.protocol_authoring.start(agent.pending)
    assert not fake.writes()


def test_expiry_and_changes_block_creation(system):
    fake,agent,_=system;identity=draft(system)
    agent.protocol_authoring.propose(identity,'create')
    agent.pending['at']=time.time()-601
    agent.confirm_from_chat('Yes');assert not fake.writes()
    agent.protocol_authoring.propose(identity,'create')
    fake.h.session='new-session'
    with pytest.raises(TeachingError,match='connection'):agent.confirm_from_chat('Yes')
    assert not fake.writes()


def test_uncertain_creation_is_not_repeated(system):
    fake,agent,_=system;identity=draft(system);fake.fail_path='protocols'
    # Fail the POST only, after the read-only checks.
    original=fake.h.request
    def request(method,path,body):
        if method=='POST' and path=='protocols':
            fake.calls.append((method,path,body));raise TimeoutError('injected timeout')
        saved=fake.fail_path;fake.fail_path=None
        try:return original(method,path,body)
        finally:fake.fail_path=saved
    fake.h.request=request
    record=approved(system,identity,'create')
    assert record['status']=='failed_or_uncertain'
    assert sum(path=='protocols' for _,path,_ in fake.writes())==1
    assert (fake.h.folder/'active.json').exists()
    with pytest.raises(TeachingError):agent.protocol_authoring.propose(identity,'create')


@pytest.mark.parametrize('scenario',['wrong-mode','stale-job','timeout'])
def test_simulation_fail_closed_without_retry(system,scenario):
    fake,agent,_=system;identity=draft(system);approved(system,identity,'create')
    if scenario=='wrong-mode':fake.non_simulation=True
    elif scenario=='stale-job':fake.job='old-job'
    else:
        fake.unknown=True
        ticks=iter([0,1,2,901]);agent.protocol_authoring.clock=lambda:next(ticks)
    record=approved(system,identity,'simulate')
    assert record['status']=='failed_or_uncertain' and not fake.h.settings()['recipes']
    assert sum(path=='protocol-run/create' for _,path,_ in fake.writes())==1
    assert not any(path.endswith('abort') for _,path,_ in fake.writes())
    assert (fake.h.folder/'active.json').exists()
    with pytest.raises(TeachingError):agent.protocol_authoring.propose(identity,'simulate')


def test_changed_native_protocol_cannot_be_commissioned(system):
    fake,agent,_=system;identity=draft(system);approved(system,identity,'create');approved(system,identity,'simulate')
    fake.protocol['steps'][0]['dispenseSettings']['useOffset']=True
    with pytest.raises(TeachingError):agent.protocol_authoring.propose(identity,'commission','wrong')
    assert not fake.h.settings()['recipes']


def test_report_must_match_every_well_and_volume(system):
    fake,agent,_=system;identity=draft(system);created=approved(system,identity,'create')
    result=result_for(fake.protocol,fake.compiled)
    verify_simulation(result,'new-job',fake.protocol,fake.compiled)
    result['runtimeSteps'][1]['pipetteActivities'][0]['target'][0]['well']='D6'
    with pytest.raises(TeachingError,match='wells or volumes'):
        verify_simulation(result,'new-job',fake.protocol,fake.compiled)


def test_native_validation_failure_does_not_simulate(system):
    fake,agent,_=system;identity=draft(system)
    original=fake.h.request
    def request(method,path,body):
        result=original(method,path,body)
        if path=='protocols/validate/101':fake.protocol['isValid']=False
        return result
    fake.h.request=request
    record=approved(system,identity,'create')
    assert record['status']=='failed_or_uncertain'
    assert not any(path=='protocol-run/create' for _,path,_ in fake.writes())


def test_log_failure_stops_and_never_dispatches(system):
    fake,agent,_=system;identity=draft(system)
    agent.protocol_authoring.propose(identity,'create')
    agent.protocol_authoring.save=Mock(side_effect=PermissionError('Evidence inaccessible'))
    agent.confirm_from_chat('Yes');agent.get_runner()._thread.join(5)
    assert not fake.writes() and agent.run_state['active'] is False
    assert 'Evidence inaccessible' in agent.run_state['error']


def test_commissioned_inventory_is_consumed_once(system):
    fake,agent,_=system;identity=draft(system)
    approved(system,identity,'create');approved(system,identity,'simulate');approved(system,identity,'commission','one_cycle')
    recipe=fake.h.settings()['recipes']['one_cycle']
    load=fake.h.reserve_inventory(recipe,{'request_id':'test-run'})
    assert len(load['load_complete']['residualTips'][0]['residualTipData']['addresses'])==4
    with pytest.raises(TeachingError,match='exhausted'):fake.h.reserve_inventory(recipe,{'request_id':'second'})


def test_stop_before_create_does_not_send_anything(system):
    fake,agent,_=system;identity=draft(system)
    agent.protocol_authoring.propose(identity,'create')
    plan=deepcopy(agent.pending);plan['confirmation_source']='researcher_chat'
    run=Mock();run.stopped.return_value=True
    result=agent.protocol_authoring.execute(run,plan)
    assert not result['ok'] and not fake.writes()
