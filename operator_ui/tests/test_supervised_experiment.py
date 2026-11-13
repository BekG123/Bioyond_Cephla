import json
from pathlib import Path
import sys
from unittest.mock import Mock,patch
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from supervised_experiment import split_handling,build_steps,CellvisExperiment
from lacry_experiment import ExperimentApi,TOOLS


def fixture_steps(cycles=1):
    result=[]
    for cycle in range(1,cycles+1):
        for station in ('hamilton','squid'):
            for kind,label in [('queue','Travel forward'),('jaws','Open jaws'),('queue','Empty HOME clearance'),
                               ('instrument','Check destination before retrieval'),('queue','Travel forward'),
                               ('jaws','Close jaws'),('queue','Released HOME clearance')]:
                result.append(dict(kind=kind,label=label,cycle=cycle,station=station))
    return result


def test_split_preserves_every_motion_in_order():
    source=fixture_steps(3)
    groups=split_handling(source,3)
    assert [s for g in groups for s in g['delivery']+g['retrieval']]==source
    steps=build_steps(groups,'P1',{'recipe':{'protocol_hash':'HASH'}},{'profile_hash':'IMAGE'})
    assert len(steps)==21
    assert [s['operation'] for s in steps[:7]]==['deliver','protocol','retrieve','prepare_loading','deliver','image','retrieve']
    assert steps[0]['transfer']=={'plate':'P1','from':'bioyond deck','to':'hamilton'}
    assert steps[-1]['transfer']=={'plate':'P1','from':'squid stage','to':'bioyond deck'}


def test_changed_checkpoint_blocks():
    steps=fixture_steps();steps[2]['label']='Different clearance'
    with pytest.raises(Exception,match='checkpoint'):split_handling(steps,1)


def test_no_model_tool_can_grant_or_execute():
    assert {t['name'] for t in TOOLS}=={'propose_experiment_plan','experiment_status','find_experiments'}


def test_uncommissioned_recipe_blocks_before_arm_access():
    backend=Mock();registry=Mock();imaging=Mock()
    registry.get.return_value={'scan_count':1,'metadata':{'plate_type':'Cellvis P24-1.5H-N'}}
    backend.instrument.prepare.side_effect=RuntimeError('No commissioned recipe')
    adapter=CellvisExperiment(backend,registry,imaging)
    with pytest.raises(RuntimeError,match='commissioned'):adapter.preview('P1','missing')
    backend.s.status.assert_not_called();imaging.prepare.assert_not_called()


def test_unregistered_and_wrong_profile_block():
    backend=Mock();registry=Mock()
    adapter=CellvisExperiment(backend,registry,Mock())
    for plate in ({'scan_count':0},{'scan_count':1,'metadata':{'plate_type':'Falcon 48'}}):
        registry.get.return_value=plate
        with pytest.raises(Exception):adapter.preview('P1','recipe')
    backend.instrument.prepare.assert_not_called()


def test_reviewed_48_well_recipe_cannot_run_on_cellvis():
    backend=Mock();registry=Mock();imaging=Mock()
    registry.get.return_value={'scan_count':1,'metadata':{'plate_type':'Cellvis P24-1.5H-N'}}
    backend.instrument.prepare.return_value={'recipe':{'reviewed':True,'plate_profile':'Falcon 48-well','transported_plate_site':4}}
    with pytest.raises(Exception,match='48-well recipe'):
        CellvisExperiment(backend,registry,imaging).preview('P1','wrong-profile')
    imaging.prepare.assert_not_called()


def test_direct_start_without_human_source_is_refused(tmp_path):
    api=ExperimentApi(Mock(),folder=tmp_path)
    with pytest.raises(Exception,match='human confirmation'):api.start({})
    assert not list(tmp_path.iterdir())


def test_proposal_refusal_is_visible_not_stale_pending(tmp_path):
    import threading
    agent=Mock();agent.lock=threading.RLock();agent.review=None
    agent.get_runner.return_value=Mock(active=False,reserved=False)
    agent.pending={'old':'unsafe to reuse'}
    adapter=Mock();adapter.preview.side_effect=RuntimeError('No commissioned recipe')
    api=ExperimentApi(agent,folder=tmp_path,adapter=adapter)
    text,error=api.run_tool('propose_experiment_plan',{'plate_id':'P1','recipe':'missing'})
    assert error and 'commissioned' in text
    assert agent.pending is None


def test_real_accepted_routes_are_only_partitioned():
    from cellvis24_workflow import compile_steps,evidence
    source=compile_steps(['hamilton','squid'],1,recorded_hamilton_variant='opposite3')
    groups=split_handling(source,1)
    assert [s for g in groups for s in g['delivery']+g['retrieval']]==source
    assert len(evidence())==64


def test_preview_does_not_write_capability_registers():
    backend=Mock();registry=Mock();imaging=Mock()
    registry.get.return_value={'scan_count':1,'metadata':{'plate_type':'Cellvis P24-1.5H-N'}}
    backend.instrument.prepare.return_value={'recipe':{'protocol_hash':'reviewed','plate_profile':'Cellvis P24-1.5H-N','transported_plate_site':4}}
    backend.s.envelope={}
    imaging.prepare.return_value={'profile_hash':'selected'}
    adapter=CellvisExperiment(backend,registry,imaging)
    with patch('cellvis24_workflow.plan',return_value={'steps':fixture_steps()}) as motion:
        adapter.preview('P1','recipe')
    assert motion.call_args.kwargs['probe'] is False
    assert motion.call_args.kwargs['check_stations'] is False
    backend.s.robot.set_sys_var_i.assert_not_called()


def test_hamilton_wait_is_exact_job_and_before_completion_permission():
    backend=Mock();adapter=CellvisExperiment(backend,Mock(),Mock())
    adapter.motion={'start':{}};adapter.at_home=Mock();adapter.actual_run=Mock()
    scheduler=Mock();scheduler.run.plan={'hamilton':{'protocol':'reviewed'},'plate_id':'P1','plate_record':{'revision':1}}
    adapter.registry.get.return_value={'revision':1}
    backend.instrument.start.return_value={'job_id':'owned-job'}
    backend.instrument.wait.return_value={'ok':True}
    backend.instrument.completed_for_pickup.side_effect=RuntimeError('Stale native completion')
    with pytest.raises(RuntimeError,match='Stale'):
        adapter.dispatch({'id':'s2','machine':'hamilton_prep','operation':'protocol'},scheduler)
    assert backend.instrument.wait.call_args.args[1]=={'job_id':'owned-job'}
    assert 'hamilton_completed' not in adapter.ticket


def test_retrieval_without_completion_never_reaches_motion():
    backend=Mock();adapter=CellvisExperiment(backend,Mock(),Mock())
    accepted={'steps':fixture_steps(),'acceptance_sha256':'A'}
    scheduler=Mock();scheduler.run.plan={'motion':accepted,'cycles':1}
    with patch('cellvis24_workflow.compile_steps',return_value=accepted['steps']), patch('cellvis24_workflow.evidence',return_value='A'):
        with pytest.raises(Exception,match='exact-job'):
            adapter._handling({'id':'r','operation':'retrieve','params':{'station':'hamilton'}},scheduler,lambda:False)
    backend.s.move_gripper.assert_not_called()


def test_lacry_one_yes_runs_bound_fake_plan_and_reports_cycle_two_fault(tmp_path):
    import time
    from lacry_agent import LacryAgent
    from sequences import Runner
    from labfacade.supervised import Operation
    runner=Runner()
    agent=LacryAgent(Mock(),Mock(),lambda:runner,client=Mock())
    agent.public=Mock(return_value={'ok':True})
    calls=[]
    steps=[dict(id=str(i),machine='fake_lab',operation='cycle',kind='experiment',label=f'Cycle {i}',
                params={'cycle':i},resources=['lab']) for i in range(1,4)]
    now=time.time()
    spec=dict(title='Fake single-plate experiment',plate_id='P1',plates={'P1':'bioyond deck'},cycles=3,
        window={'not_before':now,'expires_at':now+3600},steps=steps,
        hamilton={'protocol':'reviewed','recipe':{'protocol_id':12,'protocol_hash':'fake-fixture-hash'}},
        imaging={'profile_hash':'fake-image-settings','profile':{}},plate_record={'revision':1})
    adapter=Mock();adapter.preview.return_value=spec
    def execute(step,scheduler):
        calls.append(step['id'])
        if step['id']=='2':raise TimeoutError('Exact-job timeout fixture')
        return {'ok':True}
    adapter.operations.return_value=[Operation('fake_lab','cycle',('lab',),'fake only',execute)]
    api=ExperimentApi(agent,folder=tmp_path,adapter=adapter)
    agent.experiment_api=api
    text,error=agent._run_tool('propose_experiment_plan',{'plate_id':'P1','recipe':'reviewed','cycles':3})
    assert not error and agent.pending and calls==[]
    agent.confirm_from_chat('Yes')
    deadline=time.monotonic()+5
    while runner.active and time.monotonic()<deadline:time.sleep(.01)
    assert not runner.active and calls==['1','2']
    assert api.scheduler.run.read_json('experiment_status.json')['status']=='unknown'
    assert len([e for e in api.scheduler.run.events.read() if e.get('status')=='plan_approved'])==1
    assert agent.pending is None
    assert 'timeout' in agent.run_state['error'].lower()


@pytest.mark.parametrize('target,actual,accepted',[(1.77,1.74,True),(1.77,10.,False),
                                                (90.71661229181757,91.1,True),(90.71661229181757,92.,False)])
def test_holder_orientation_is_preserved_across_instrument_wait(target,actual,accepted):
    adapter=CellvisExperiment(Mock(),Mock(),Mock())
    home={'X':312.5,'Y':-66.3,'Z':105.72,'Rz':89.84}
    adapter.motion={'start':home,'e2':target}
    with patch('scope_step_trial.preflight',return_value={'pose_mm':home}), patch('home_hamilton_exchange.native',return_value={'external_axes':{'E1':28.,'E2':actual}}):
        if accepted:adapter.at_home()
        else:
            with pytest.raises(Exception,match='holder changed'):adapter.at_home()


def test_registry_custody_requires_receipt_and_preserves_concurrent_annotations(tmp_path):
    from plate_registry import PlateRegistry
    from labfacade.events import RunFolder
    registry=PlateRegistry(tmp_path/'plates.sqlite3')
    with registry.db() as db:
        db.execute("INSERT INTO plates(plate_id,first_seen,last_seen) VALUES ('P1','test','test')")
    run=RunFolder.create(tmp_path/'runs','test',{'plate_id':'P1','plate_record':{'revision':1}}, {})
    run.write_json('ledger.json',{'plates':{'P1':{'location':'hamilton','step':'s1'}}})
    adapter=CellvisExperiment(Mock(),registry,Mock())
    with pytest.raises(Exception,match='No completed transfer'):adapter.publish_custody(run)
    assert registry.get('P1')['revision']==1
    run.events.emit('result',step='s1',status='completed',data={'ok':True})
    adapter.publish_custody(run)
    row=registry.get('P1',history=True)
    assert row['location']=='Hamilton' and row['location_basis']=='verified_workflow_receipt'
    assert row['history'][0]['data']['operator_acceptance'] is False
    adapter.record_experiment_result(run,{'status':'paused'})
    assert registry.get('P1')['location']=='Hamilton'
    run.write_json('ledger.json',{'plates':{'P1':{'location':'unknown','step':'s2'}}})
    adapter.publish_custody(run)
    assert registry.get('P1')['location']=='unknown'
    row=registry.get('P1')
    registry.update('P1',row['revision'],{'notes':'human update'},'test operator')
    with pytest.raises(Exception,match='Plate record changed'):adapter.publish_custody(run)
    assert registry.get('P1')['metadata']['notes']=='human update'
