"""Offline integration: all instrument/motion dispatch boundaries are fakes."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
from unittest.mock import Mock
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import composed_instrument_chain as chain
from hotel_squid_composition import HotelSquidAdapter
from lacry_workflow_router import WorkflowRouter, hotel_instrument_stations
from lacry_workflow_composition import WorkflowComposition
from lacry_agent import LacryAgent


def setup(monkeypatch, stations=('Hamilton','Squid'), count=5):
    backend=Mock();squid=Mock()
    backend.instrument.prepare.return_value=dict(protocol='reviewed',session_id='h-session',timeout_s=600,
        recipe=dict(plate_profile=chain.PROFILE,transported_plate_site=4,protocol_id=1003,protocol_hash='bound'))
    squid.prepare.return_value=dict(profile_hash='squid-hash',session='s-session',profile=dict(timeout_s=86400,
        selected_settings=dict(total_images=5,channels=['BF'],nt=5,nz=1,fovs=1)))
    monkeypatch.setattr(chain,'imaging',lambda b:squid)
    request=dict(stations=list(stations),recipe='reviewed',image_count=count if 'Squid' in stations else None)
    prepared=chain.prepare(backend,request)
    return backend,squid,prepared


def test_preview_binds_existing_routes_and_read_only_tools(monkeypatch):
    backend,squid,p=setup(monkeypatch)
    from composed_cellvis_registration import delivery_steps
    assert p['timeout_s']==14400
    for g in p['groups']:
        assert g['delivery']+g['retrieval']==delivery_steps(g['station'],True)
    backend.instrument.start.assert_not_called();backend.s.move_gripper.assert_not_called()
    squid.start.assert_not_called();squid.prepare_loading.assert_not_called()
    squid.prepare.assert_called_once_with(None,allow_loading_return=True)


def test_imaging_only_needs_no_hamilton_recipe(monkeypatch):
    backend,squid,p=setup(monkeypatch,('Squid',))
    backend.instrument.prepare.assert_not_called()
    assert p['hamilton'] is None
    assert [s['id'] for s in chain.steps(p)]==[
        'instrument_squid_loading','instrument_squid_deliver','instrument_squid_run','instrument_squid_retrieve']


@pytest.mark.parametrize('count',[4,6])
def test_requested_image_count_never_silently_dropped(monkeypatch,count):
    with pytest.raises(Exception,match=f'Requested {count} images'):
        setup(monkeypatch,('Squid',),count)


def test_hamilton_missing_or_wrong_profile_recipe_stops_before_motion(monkeypatch):
    backend=Mock()
    with pytest.raises(Exception,match='commissioned'):chain.prepare(backend,dict(stations=['Hamilton']))
    backend.instrument.prepare.return_value=dict(recipe=dict(plate_profile='48 well',transported_plate_site=4))
    with pytest.raises(Exception,match='Cellvis'):chain.prepare(backend,dict(stations=['Hamilton'],recipe='wrong'))
    backend.instrument.start.assert_not_called();backend.s.status.assert_not_called()


def harness(tmp_path,monkeypatch,stations=('Hamilton','Squid')):
    backend,squid,p=setup(monkeypatch,stations)
    adapter=HotelSquidAdapter(backend=backend,registry=Mock())
    adapter.registry().get.return_value=dict(revision=3)
    spec=dict(instrument_chain=p,continuation=dict(acceptance='routes'))
    run=Mock(run_id='approved-run');run.stopped.return_value=False
    prior=dict(ok=True,record=str(tmp_path/'registration.json'),plate_id='FRESH')
    context=dict(registration=prior,plate_id='FRESH',plate_location='HOME',motion=None,tickets={},
                 home_pose={},home_e1=28,home_e2=1.77)
    monkeypatch.setattr(chain,'registration_context',lambda r:deepcopy(context))
    monkeypatch.setattr(chain,'at_home',lambda b,c:None)
    history=[]
    def handling(run,backend,spec,c,g,action):
        history.append((g['station'],action))
        c.update(plate_location='HOME' if action=='retrieval' else g['station'],motion={})
        return dict(ok=True,record='fake-motion')
    monkeypatch.setattr(chain,'handling',handling)
    def hstart(plan,plate_id,save):
        assert plate_id=='FRESH'
        ticket=dict(status='started',job_id='new-hamilton');save(ticket);return ticket
    def start(plan,folder,save,stopped):
        ticket=dict(status='started',experiment_id='new-squid');save(ticket);return ticket
    def wait(plan,ticket,save,stopped,progress):
        ticket['status']='completed';save(ticket);return dict(ok=True)
    backend.instrument.start.side_effect=hstart;backend.instrument.wait.side_effect=wait
    squid.start.side_effect=start;squid.wait.side_effect=wait
    squid.observe.return_value=dict(completion_confirmed=True)
    squid.prepare_loading.return_value=dict(ok=True)
    squid.restore_loading.return_value=dict(ok=True)
    return adapter,run,spec,prior,history,squid


def test_both_instruments_complete_then_retrieve_with_fresh_identity(tmp_path,monkeypatch):
    adapter,run,spec,prior,history,squid=harness(tmp_path,monkeypatch)
    for step in chain.steps(spec['instrument_chain']):
        prior=adapter.execute_step(run,spec,step['id'],prior)
    assert history==[('Hamilton','delivery'),('Hamilton','retrieval'),('Squid','delivery'),('Squid','retrieval')]
    assert prior['plate_id']=='FRESH' and prior['plate_location']=='HOME'
    adapter.backend.instrument.start.assert_called_once()
    assert adapter.backend.instrument.completed_for_pickup.call_count==2
    squid.start.assert_called_once();squid.restore_loading.assert_called_once()
    squid.observe.assert_called_once()
    final=json.loads(Path(prior['record']).read_text())
    assert final['context']['tickets']['Hamilton']['job_id']=='new-hamilton'
    assert final['context']['tickets']['Squid']['experiment_id']=='new-squid'


@pytest.mark.parametrize('station',['Hamilton','Squid'])
def test_timeout_retains_claim_and_never_retrieves_or_restarts(tmp_path,monkeypatch,station):
    adapter,run,spec,prior,history,squid=harness(tmp_path,monkeypatch,(station,))
    api=adapter.backend.instrument if station=='Hamilton' else squid
    api.wait.side_effect=TimeoutError('unknown outcome')
    for step in chain.steps(spec['instrument_chain']):
        if step['id'].endswith('_run'):
            with pytest.raises(TimeoutError):adapter.execute_step(run,spec,step['id'],prior)
            with pytest.raises(FileExistsError):adapter.execute_step(run,spec,step['id'],prior)
            break
        prior=adapter.execute_step(run,spec,step['id'],prior)
    assert history==[(station,'delivery')]
    api.start.assert_called_once()
    squid.restore_loading.assert_not_called()


def test_loading_failure_stops_before_delivery(tmp_path,monkeypatch):
    adapter,run,spec,prior,history,squid=harness(tmp_path,monkeypatch,('Squid',))
    squid.prepare_loading.side_effect=RuntimeError('loading reference mismatch')
    with pytest.raises(RuntimeError,match='loading reference'):
        adapter.execute_step(run,spec,'instrument_squid_loading',prior)
    assert history==[];squid.start.assert_not_called()


def test_changed_exact_job_blocks_retrieval(tmp_path,monkeypatch):
    adapter,run,spec,prior,history,squid=harness(tmp_path,monkeypatch,('Squid',))
    steps=chain.steps(spec['instrument_chain'])
    for step in steps[:-1]:prior=adapter.execute_step(run,spec,step['id'],prior)
    squid.observe.side_effect=RuntimeError('different job')
    with pytest.raises(RuntimeError,match='different job'):
        adapter.execute_step(run,spec,steps[-1]['id'],prior)
    assert history==[('Squid','delivery')]


def test_predecessor_cannot_cross_run_or_skip_step(tmp_path,monkeypatch):
    adapter,run,spec,prior,history,squid=harness(tmp_path,monkeypatch,('Squid',))
    prior=adapter.execute_step(run,spec,'instrument_squid_loading',prior)
    with pytest.raises(Exception,match='predecessor'):
        adapter.execute_step(run,spec,'instrument_squid_retrieve',prior)
    run.run_id='different-run'
    with pytest.raises(Exception,match='predecessor'):
        adapter.execute_step(run,spec,'instrument_squid_deliver',prior)
    assert history==[]


@pytest.mark.parametrize('ops,expected',[
    (['retrieve_hotel','register_plate','deliver_squid','squid_image','retrieve_squid','return_HOME'],['Squid']),
    (['retrieve_hotel','register_plate','hamilton_protocol','return_HOME'],['Hamilton']),
    (['retrieve_hotel','register_plate','hamilton_protocol','deliver_squid','squid_image','retrieve_squid','return_HOME'],['Hamilton','Squid']),
    (['retrieve_hotel','return_HOME','register_plate','return_HOME','hamilton_protocol','return_HOME','deliver_squid','squid_image','retrieve_squid','return_HOME'],['Hamilton','Squid']),
    (['retrieve_hotel','register_plate','deliver_squid','return_HOME','squid_image'],['Squid']),
    (['retrieve_hotel','register_plate','squid_image','arm_full_calibration'],None)])
def test_router_preserves_complete_order(ops,expected):
    assert hotel_instrument_stations(ops)==expected
    if expected:
        a=Mock();a.lock=threading.RLock()
        WorkflowRouter(a).propose(ops,plate_profile=chain.PROFILE,source_slot=1,recipe='reviewed' if 'Hamilton' in expected else None,
                                  image_count=5 if 'Squid' in expected else None)
        request=a.workflow_composition.propose.call_args.kwargs['instrument_request']
        assert request['stations']==expected
        assert request['image_count']==(5 if 'Squid' in expected else None)
        a.confirm.assert_not_called()


def test_ui_plan_shows_protocol_and_images_in_one_confirmation(tmp_path,monkeypatch):
    backend,squid,p=setup(monkeypatch)
    a=Mock();a.lock=threading.RLock();a.review=None;a.lab_api.active=False
    a.get_runner.return_value=Mock(active=False,reserved=False)
    a._plan_view=LacryAgent._plan_view
    adapter=Mock();adapter.preview.return_value=dict(instrument_chain=p)
    adapter.steps.return_value=chain.steps(p)
    api=WorkflowComposition(a,adapter,tmp_path)
    result=api.propose(chain.PROFILE,1,'Hamilton',instrument_request=p['request'])
    view=result['plan']
    assert result['awaiting_confirmation'] and not result['blocked']
    assert view['protocol_review']['squid']['settings']['total_images']==5
    assert view['protocol_review']['hamilton']['protocol_hash']=='bound'
    assert 'return the plate HOME' in view['summary']
    assert not any(r.startswith('Handling only') for r in view['requirements'])
    with pytest.raises(Exception,match='human Yes'):api.start(a.pending)
    adapter.execute_step.assert_not_called()


def test_autonomous_workflow_has_no_presence_expiry_or_heartbeat(tmp_path):
    now=[1000.]
    a=Mock();a.lock=threading.RLock();a.get_runner.return_value=Mock(active=True)
    a.get_runner.return_value.name='lacry_workflow_composition'
    api=WorkflowComposition(a,Mock(),tmp_path,clock=lambda:now[0])
    api.execution=dict(run_id='approved',run_folder=str(tmp_path))
    assert api.public()['execution_mode']=='autonomous'
    now[0]+=301
    assert api.public()['active']
    assert not hasattr(api,'heartbeat')
    assert not hasattr(api,'presence_current')


def test_real_hotel_preview_binds_instruments_without_dispatch(monkeypatch):
    import hotel_squid_composition as hotel
    import home_hamilton_exchange as exchange
    import cellvis24_workflow as workflow
    backend,squid,p=setup(monkeypatch,('Squid',))
    _,_,g=hotel.hotel(1)
    backend.params.return_value=g['cfg'];backend.s.envelope=g['envelope']
    state=dict(pose_mm=g['home'],joints=dict(J1=1,J2=2,J3=3,J4=4))
    monkeypatch.setattr(hotel,'preflight',lambda service:state)
    monkeypatch.setattr(exchange,'native',lambda service:dict(moving=False,external_axes=dict(E1=28,E2=1.77)))
    old_loading=Mock(side_effect=AssertionError('Planning may bind an approved stage loading return'))
    monkeypatch.setattr(workflow,'squid_ready',old_loading)
    adapter=HotelSquidAdapter(backend=backend,registry=Mock())
    spec=adapter.preview(None,1,'Squid',chain.PROFILE,instrument_request=p['request'])
    adapter.verify(spec)
    assert [s['id'] for s in adapter.steps(spec)]==['retrieve_hotel','register_barcode']+[s['id'] for s in chain.steps(p)]
    backend.s.move_gripper.assert_not_called();squid.start.assert_not_called()
    squid.prepare_loading.assert_not_called();old_loading.assert_not_called()


def test_same_accepted_phases_drive_delivery_and_retrieval(tmp_path,monkeypatch):
    import cellvis24_workflow as workflow
    import composed_cellvis_registration as registration
    import scope_step_trial
    backend,squid,p=setup(monkeypatch,('Squid',))
    group=p['groups'][0];backend.params.return_value={};backend.s.envelope={}
    monkeypatch.setattr(workflow,'evidence',lambda:'accepted')
    monkeypatch.setattr(workflow,'validate_steps',Mock())
    monkeypatch.setattr(scope_step_trial,'preflight',lambda service:dict(pose_mm={},joints={}))
    spec=dict(continuation=dict(acceptance='accepted'),geometry=dict(cfg={},envelope={}))
    context=dict(registration={'record':'scan'},motion=None,home_e1=28,home_e2=1.77)
    n=[0]
    def receipt(status,plan,e1):
        n[0]+=1;path=tmp_path/f'motion{n[0]}.json'
        path.write_text(json.dumps(dict(status=status,payload='empty',plan=plan,final=dict(pose_mm={}),
            final_native=dict(external_axes=dict(E1=e1,E2=1.77)))))
        return dict(ok=True,record=str(path))
    outbound=Mock(return_value=receipt('experiment_delivery_complete',dict(id='first',steps=group['delivery']),7))
    monkeypatch.setattr(registration,'deliver',outbound)
    def execute(run,s,cfg,approved,fresh,cam,**kwargs):
        assert approved['steps']==group['retrieval'] and approved['source'] is None
        assert kwargs['initial_e1']==7 and kwargs['ends_held'] is False
        return receipt('completed',approved,28)
    returning=Mock(side_effect=execute);monkeypatch.setattr(workflow,'execute_checked_steps',returning)
    chain.handling(Mock(),backend,spec,context,group,'delivery')
    assert context['plate_location']=='Squid' and context['home_e1']==7
    chain.handling(Mock(),backend,spec,context,group,'retrieval')
    assert context['plate_location']=='HOME' and context['home_e1']==28
    assert outbound.call_count==returning.call_count==1


def test_receipt_edit_and_registry_edit_block_next_step(tmp_path,monkeypatch):
    adapter,run,spec,prior,history,squid=harness(tmp_path,monkeypatch,('Squid',))
    prior=adapter.execute_step(run,spec,'instrument_squid_loading',prior)
    path=Path(prior['record']);original=path.read_bytes()
    path.write_text('{}')
    with pytest.raises(Exception,match='receipt changed'):
        adapter.execute_step(run,spec,'instrument_squid_deliver',prior)
    path.write_bytes(original)
    adapter.registry().get.return_value=dict(revision=4)
    with pytest.raises(Exception,match='registry changed'):
        adapter.execute_step(run,spec,'instrument_squid_deliver',prior)
    assert history==[]
