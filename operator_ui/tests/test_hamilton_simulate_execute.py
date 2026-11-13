"""Single approval simulation/live transition, using only an in-memory instrument."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from unittest.mock import Mock, MagicMock
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_dilution_authoring import system, result_for
from test_hamilton_api_catalog import addition_spec
from researcher_teaching import TeachingError
from lacry_agent import TOOLS


@pytest.fixture
def experiment(system):
    fake,agent,runner=system
    ex=agent.hamilton_experiment
    ex.arm_checkpoint=Mock(return_value=dict(X=312.5,Y=-66.3,Z=105.72,Rz=89.84))
    fake.h.require_calibration=Mock()
    stream=MagicMock();stream.__enter__.return_value=stream
    fake.h.events=lambda _:stream
    fake.h.finish_abort=Mock()  # No actual abort I/O in failure tests.
    original=fake.request
    fake.simulation=True
    def request(method,path,body=None):
        if method=='POST' and path=='protocol-run/create':
            fake.calls.append((method,path,deepcopy(body)))
            fake.simulation=body['simulate'];fake.job='simulation-job' if fake.simulation else 'physical-job'
            fake.loaded=False;fake.running=True
            return {'ok':True}
        if path=='protocol-run':
            fake.calls.append((method,path,deepcopy(body)))
            if not fake.running:return dict(runDatalId='old-job',isRunInProgress=False,protocolRunState=0,protocolId=0)
            return dict(runDatalId=fake.job,isRunInProgress=not fake.loaded,protocolRunState=0 if fake.loaded else 20,
                protocolId=0 if fake.loaded else 101,isSimulation=fake.simulation)
        if path.startswith('run-data/'):
            fake.calls.append((method,path,deepcopy(body)))
            result=result_for(fake.protocol,fake.compiled)
            result.update(id=fake.job,deviceSerialNumber='Simulation' if fake.simulation else 'fixture')
            if fake.unknown:result['runResult']='Failed'
            return result
        return original(method,path,body)
    fake.h.request=request
    def status(fresh=False):
        return dict(connected=True,global_state='Idle' if not fake.running or fake.loaded else 'Running',
            run=request('GET','protocol-run'),pending_errors=[],initialized=True,parked=True)
    fake.h.status=status
    identity=agent.protocol_authoring.draft(addition_spec())['draft_id']
    fake.compiled=agent.protocol_authoring.read(identity)['compiled']
    return fake,agent,runner,identity


def propose(experiment):
    fake,agent,runner,identity=experiment
    agent.hamilton_experiment.propose(identity,'fixture-plate')
    return deepcopy(agent.pending)


def approve(experiment):
    fake,agent,runner,identity=experiment
    agent.confirm_from_chat('Yes');runner._thread.join(5)
    assert not runner.active
    return agent.protocol_authoring.read(identity)


def starts(fake):return [body for method,path,body in fake.calls if method=='POST' and path=='protocol-run/create']


def test_one_yes_simulates_then_runs_without_commission(experiment):
    fake,agent,runner,identity=experiment
    propose(experiment)
    assert not fake.writes()
    assert agent.pending['protocol_review']['physical_execution_authorized']
    record=approve(experiment)
    assert record['status']=='experiment_completed',agent.run_state
    assert [b['simulate'] for b in starts(fake)]==[True,False]
    assert fake.h.settings()['recipes']=={}
    assert record['physical_result']['job_id']=='physical-job'
    assert record['physical_ticket']['plate_id']=='fixture-plate'
    assert fake.h.inventory_used(record['execution_binding']['recipe'])==1
    assert agent.pending is None and agent.review is None
    with pytest.raises(TeachingError):agent.hamilton_experiment.propose(identity,'fixture-plate')


def test_failed_simulation_never_runs_live(experiment):
    fake,agent,runner,identity=experiment;propose(experiment);fake.unknown=True
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert [b['simulate'] for b in starts(fake)]==[True]
    assert 'physical_ticket' not in record


def test_creation_timeout_does_not_simulate_or_retry(experiment):
    fake,agent,runner,identity=experiment;propose(experiment);fake.fail_path='protocols'
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert starts(fake)==[]


def test_changed_protocol_after_simulation_blocks_live(experiment):
    fake,agent,runner,identity=experiment;propose(experiment)
    original=agent.protocol_authoring.simulate
    def change(*args):
        original(*args);fake.protocol['name']='changed-after-simulation'
    agent.protocol_authoring.simulate=change
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert [b['simulate'] for b in starts(fake)]==[True]


def test_stop_after_simulation_blocks_live(experiment):
    fake,agent,runner,identity=experiment;propose(experiment)
    original=agent.protocol_authoring.simulate
    def stop(record,ticket,check,run):
        original(record,ticket,check,run);run.request_stop()
    agent.protocol_authoring.simulate=stop
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert [b['simulate'] for b in starts(fake)]==[True]


@pytest.mark.parametrize('change',[
    lambda p:p.pop('confirmation_source',None),lambda p:p.update(at=time.time()-601),
    lambda p:p.update(session_id='changed'),lambda p:p.update(draft_hash='changed')])
def test_requires_bound_single_use_human_approval(experiment,change):
    fake,agent,runner,identity=experiment;plan=propose(experiment)
    plan['confirmation_source']='researcher_chat';change(plan)
    with pytest.raises(TeachingError):agent.hamilton_experiment.start(plan)
    assert not fake.writes()


def test_stale_simulation_job_blocks_physical_start(experiment):
    fake,agent,runner,identity=experiment;propose(experiment)
    original=fake.h.request
    def request(method,path,body=None):
        result=original(method,path,body)
        if path.startswith('run-data/'):result['id']='old-job'
        return result
    fake.h.request=request
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert [b['simulate'] for b in starts(fake)]==[True]


def test_simulation_timeout_blocks_physical_start(experiment):
    fake,agent,runner,identity=experiment;propose(experiment)
    agent.protocol_authoring.clock=Mock(side_effect=[0,901])
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert [b['simulate'] for b in starts(fake)]==[True]
    assert (fake.h.folder/'active.json').exists()


def test_inventory_config_change_after_simulation_blocks_live(experiment):
    fake,agent,runner,identity=experiment;propose(experiment)
    original=agent.protocol_authoring.simulate
    def change(*args):
        original(*args)
        settings=fake.h.settings();settings['timeout_s']=120
        fake.config.write_text(json.dumps(settings))
    agent.protocol_authoring.simulate=change
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert [b['simulate'] for b in starts(fake)]==[True]


def test_physical_start_timeout_is_not_resent(experiment):
    fake,agent,runner,identity=experiment;propose(experiment)
    original=fake.h.request
    def request(method,path,body=None):
        result=original(method,path,body)
        if method=='POST' and path=='protocol-run/create' and body['simulate'] is False:
            raise TimeoutError('injected live start uncertainty')
        return result
    fake.h.request=request
    record=approve(experiment)
    assert record['status']=='failed_or_uncertain'
    assert [b['simulate'] for b in starts(fake)]==[True,False]
    assert fake.h.inventory_used(record['execution_binding']['recipe'])==1
    assert (fake.h.folder/'active.json').exists()


def test_tool_is_exposed():
    assert 'plan_hamilton_experiment' in {t['name'] for t in TOOLS}
