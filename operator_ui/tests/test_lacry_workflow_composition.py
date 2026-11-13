from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
from unittest.mock import Mock
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lacry_workflow_composition import WorkflowComposition, composition_outline
from lacry_workflow_router import WorkflowRouter
from lacry_agent import LacryAgent, TOOLS


def agent():
    a=Mock();a.lock=threading.RLock();a.review=None;a.pending=None
    a.lab_api.active=False;a.get_runner.return_value=Mock(active=False,reserved=False)
    a.run_state=dict(active=False,done=[])
    a._plan_view=LacryAgent._plan_view
    return a


def test_cellvis_slot_chain_keeps_scan_without_requiring_prior_identity(tmp_path):
    a=agent();adapter=Mock();api=WorkflowComposition(a,adapter,tmp_path)
    adapter.preview.return_value=dict(plate_id=None,slot=1,destination='Squid')
    adapter.steps.return_value=composition_outline('Cellvis P24-1.5H-N',1,'Squid')[0]
    result=api.propose('Cellvis P24-1.5H-N',1,'Squid')
    assert not result['blocked'] and result['awaiting_confirmation']
    assert [s['id'] for s in result['workflow_steps']]==['retrieve_hotel','register_barcode','deliver_squid']
    assert all('needs a supervised profile validation' not in b for b in result['plan']['blockers'])
    assert result['workflow_steps'][0]['qualification']=='accepted'
    assert a.pending['composition']['plate_id'] is None
    adapter.preview.assert_called_once_with(None,1,'Squid','Cellvis P24-1.5H-N')
    adapter.execute_step.assert_not_called()
    with pytest.raises(Exception,match='human Yes'):api.start(a.pending)


def test_48well_cannot_silently_use_cellvis_registration():
    steps,blockers=composition_outline('48_well_projected_20261026',1,'Squid')
    assert steps[1]['qualification']=='needs_profile_validation'
    assert any('48-well' in b and 'scanner' in b for b in blockers)


def test_router_automatically_includes_registration_for_hotel_delivery(tmp_path):
    a=agent();adapter=Mock();a.workflow_composition=WorkflowComposition(a,adapter,tmp_path)
    adapter.preview.return_value=dict(plate_id=None,slot=1,destination='Squid')
    adapter.steps.return_value=composition_outline('Cellvis P24-1.5H-N',1,'Squid')[0]
    router=WorkflowRouter(a)
    result=router.propose(['retrieve_hotel','deliver_squid'],
        plate_profile='Cellvis P24-1.5H-N',source_slot=1)
    assert result['awaiting_confirmation']
    assert any(s['id']=='register_barcode' for s in a.pending['steps'])
    a.automatic_workflow.assert_not_called()


def test_maintenance_chain_delegates_whole_order_once():
    a=agent();a.command_batch_workflow.return_value.propose.return_value=dict(id='batch',steps=[],executable=True)
    commands=['hamilton_self_calibration','hamilton_channel_calibration','arm_full_calibration']
    result=WorkflowRouter(a).propose(commands)
    assert result['awaiting_confirmation']
    a.command_batch_workflow.return_value.propose.assert_called_once_with(commands)
    a.confirm.assert_not_called()


def test_protocol_imaging_chain_preserves_recipe_cycles_and_settings():
    a=agent();router=WorkflowRouter(a)
    router.propose(['hamilton_protocol','squid_image'],plate_profile='Cellvis P24-1.5H-N',
                   plate_id='P1',recipe='reviewed-dilution',cycles=5,imaging_profile='selected',purpose='Cells')
    a.experiment_api.propose.assert_called_once_with('P1','reviewed-dilution',5,'selected','Cells')
    a.confirm.assert_not_called()


def test_imaging_chain_has_one_proposal_with_all_repetitions():
    a=agent();a.automatic_workflow.return_value.propose.return_value=dict(id='imaging',steps=[])
    WorkflowRouter(a).propose(['deliver_squid','squid_image','retrieve_squid'],cycles=3,plate_profile='48_well_projected_20261026')
    a.automatic_workflow.return_value.propose.assert_called_once_with(
        protocol=None,retrieve=True,pickup_from_calibration=False,repetitions=3)


def test_no_partial_execution_or_dropped_goals_for_unknown_chain():
    a=agent();operations=['hamilton_protocol','arm_full_calibration','squid_image']
    result=WorkflowRouter(a).propose(operations,cycles=4)
    assert result['blocked'] and not result['awaiting_confirmation']
    assert result['plan']['labels']==operations and result['plan']['repetitions']==4
    a.experiment_api.propose.assert_not_called();a.confirm.assert_not_called()


def test_cellvis_does_not_fall_through_to_48well_imaging_adapter():
    a=agent()
    result=WorkflowRouter(a).propose(['arm_full_calibration','deliver_squid','squid_image','retrieve_squid'],
                                   plate_profile='Cellvis P24-1.5H-N')
    assert result['blocked']
    a.automatic_workflow.assert_not_called()


@pytest.mark.parametrize('cycles',[0,True,1.5,21])
def test_bad_cycles_clear_stale_plan(cycles):
    a=agent();a.pending={'old':'plan'}
    with pytest.raises(Exception,match='Cycles'):WorkflowRouter(a).propose(['squid_image'],cycles=cycles)
    assert a.pending is None


def ready_composition(tmp_path):
    a=agent();adapter=Mock();spec=dict(plate_id='P1',slot=1,destination='HOME')
    adapter.preview.return_value=spec
    adapter.steps.return_value=[dict(id='retrieve_hotel',label='Retrieve to HOME')]
    adapter.require.side_effect=lambda result: result if result.get('ok') else (_ for _ in ()).throw(RuntimeError('uncertain'))
    api=WorkflowComposition(a,adapter,tmp_path)
    api.propose('48_well_projected_20261026',1,'HOME','P1')
    return a,adapter,api


def test_human_approval_single_use_and_no_model_authority(tmp_path):
    a,adapter,api=ready_composition(tmp_path)
    with pytest.raises(Exception,match='human Yes'):api.start(a.pending)
    a.pending['confirmation_source']='researcher_chat'
    plan=deepcopy(a.pending);a.get_runner.return_value.start.return_value={'ok':True}
    api.start(plan)
    assert a.pending is None
    with pytest.raises(Exception,match='consumed'):api.start(plan)
    a.get_runner.return_value.start.assert_called_once()
    adapter.execute_step.assert_not_called()


def test_timeout_retains_uncertainty_and_stops_remaining_steps(tmp_path):
    a,adapter,api=ready_composition(tmp_path)
    plan=deepcopy(a.pending)
    plan['steps'].append(dict(id='must_not_run',kind='workflow',label='Later step'))
    adapter.execute_step.side_effect=TimeoutError('unknown physical state')
    run=Mock();run.stopped.return_value=False
    with pytest.raises(TimeoutError):api.execute(run,plan,tmp_path/'run.json')
    adapter.execute_step.assert_called_once()
    assert (tmp_path/'unresolved.json').exists()
    assert json.loads((tmp_path/'run.json').read_text())['status']=='stopped_or_uncertain'
    with pytest.raises(Exception,match='unresolved'):api.idle()
    assert not a.run_state['active']


def test_stop_before_first_dispatch_releases_only_own_hold(tmp_path):
    a,adapter,api=ready_composition(tmp_path)
    plan=deepcopy(a.pending)
    run=Mock();run.stopped.return_value=True
    with pytest.raises(Exception,match='Transfer stopped'):
        api.execute(run,plan,tmp_path/'run.json')
    adapter.execute_step.assert_not_called()
    assert not (tmp_path/'unresolved.json').exists()
    record=json.loads((tmp_path/'run.json').read_text())
    assert record['status']=='refused_before_dispatch'
    assert record['motion_dispatch_attempted'] is False


def test_predispatch_failure_does_not_remove_someone_elses_hold(tmp_path):
    a,adapter,api=ready_composition(tmp_path)
    plan=deepcopy(a.pending)
    hold=tmp_path/'unresolved.json';hold.write_text('{"record":"other-run"}')
    run=Mock();run.stopped.return_value=False
    with pytest.raises(FileExistsError):api.execute(run,plan,tmp_path/'run.json')
    assert json.loads(hold.read_text())=={'record':'other-run'}
    adapter.execute_step.assert_not_called()


def test_success_logs_receipt_without_claiming_visual_acceptance(tmp_path):
    a,adapter,api=ready_composition(tmp_path)
    plan=deepcopy(a.pending);a.run_state=dict(done=[])
    adapter.execute_step.return_value=dict(ok=True,record='real-executor-receipt')
    run=Mock();run.stopped.return_value=False
    assert api.execute(run,plan,tmp_path/'run.json')['ok']
    record=json.loads((tmp_path/'run.json').read_text())
    assert record['operator_observation']=='pending'
    assert record['steps'][0]['result']['record']=='real-executor-receipt'
    assert not (tmp_path/'unresolved.json').exists()


@pytest.mark.parametrize('phase',['dispatching','completed'])
@pytest.mark.parametrize('persistent',[False,True])
def test_log_1175_never_replays_a_physical_step(tmp_path,monkeypatch,phase,persistent):
    from squid_bridge import state_io
    a,adapter,api=ready_composition(tmp_path)
    plan=deepcopy(a.pending);path=tmp_path/'run.json'
    path.write_text(json.dumps(dict(status='approved',plan=plan)))
    adapter.execute_step.return_value=dict(ok=True,record='executor-receipt')
    run=Mock();run.stopped.return_value=False
    replace=state_io.replace_file;failures=[]
    error=OSError('fixture WinError 1175');error.winerror=1175
    def locked(source,target):
        record=json.loads(Path(source).read_bytes())
        if record['status']=='running' and record['steps'][0]['status']==phase:
            if persistent or not failures:
                failures.append(Path(source).read_bytes());raise error
        replace(source,target)
    monkeypatch.setattr(state_io,'replace_file',locked)
    monkeypatch.setattr(state_io.time,'sleep',lambda delay:None)
    if persistent:
        with pytest.raises(OSError):api.execute(run,plan,path)
        assert (tmp_path/'unresolved.json').exists()==(phase=='completed')
        assert adapter.execute_step.call_count==(0 if phase=='dispatching' else 1)
        assert json.loads(path.read_bytes())['status']==('refused_before_dispatch' if phase=='dispatching' else 'stopped_or_uncertain')
    else:
        assert api.execute(run,plan,path)['ok']
        adapter.execute_step.assert_called_once()
        assert json.loads(path.read_bytes())['status']=='completed_controller_verified'
    assert len(set(failures))==1


def test_tools_exposed_without_approval_or_execution_arguments():
    tools={t['name']:t for t in TOOLS}
    for name in ('get_workflow_catalog','plan_workflow','plan_plate_transfer'):
        assert name in tools
        assert not set(tools[name]['input_schema']['properties']) & {'approve','execute','confirmed','override'}


def test_cellvis_slot1_home_is_executable_without_barcode(tmp_path):
    a=agent();adapter=Mock()
    adapter.preview.return_value=dict(plate_id=None,plate_profile='Cellvis P24-1.5H-N',slot=1,
                                      destination='HOME',identity_status='unregistered_pending_scan')
    adapter.steps.return_value=[dict(id='retrieve_hotel',label='Retrieve slot 1 to HOME')]
    api=WorkflowComposition(a,adapter,tmp_path)
    result=api.propose('Cellvis P24-1.5H-N',1,'HOME')
    assert result['awaiting_confirmation'] and not result['blocked']
    adapter.preview.assert_called_once_with(None,1,'HOME','Cellvis P24-1.5H-N')
    adapter.require.side_effect=lambda r:r
    adapter.execute_step.return_value=dict(ok=True,record='retrieval-receipt')
    run=Mock();run.stopped.return_value=False
    assert api.execute(run,deepcopy(a.pending),tmp_path/'run.json')['ok']
    adapter.registry.assert_not_called()
    record=json.loads((tmp_path/'run.json').read_text())
    assert record['identity_status']=='unregistered_pending_scan'


def test_cellvis_acceptance_matches_unchanged_real_retrieval_geometry():
    from hotel_squid_composition import hotel,profile_binding
    from run_hotel_slot1_workflow import digest
    _,workflow,geometry=hotel(1)
    binding=profile_binding('Cellvis P24-1.5H-N',1)
    assert binding['basis']=='operator_confirmation_of_previous_testing'
    assert digest(geometry)==binding['geometry_sha256']==workflow['geometry_sha256']['retrieve']


@pytest.mark.parametrize('plate_id',[None,'KNOWN'])
def test_real_adapter_previews_cellvis_then_calls_existing_retrieval(monkeypatch,plate_id):
    import hotel_squid_composition as module
    from unittest.mock import patch
    a=agent();backend=a.backend
    actual,workflow,geometry=module.hotel(1)
    s=dict(pose_mm=geometry['home'],joints=dict(J1=100,J2=1,J3=2,J4=3))
    n=dict(moving=False,external_axes=dict(E1=28,E2=1.77))
    backend.params.return_value=geometry['cfg'];backend.s.envelope=geometry['envelope']
    backend.s.move_gripper.return_value=dict(ok=True)
    adapter=module.HotelSquidAdapter(a)
    plate=dict(metadata=dict(plate_type='Cellvis P24-1.5H-N'),scan_count=1,
               location='rack:1/slot:1',revision=1)
    a.memory.plates.get.return_value=plate
    # Custody invalidation changes revision: it must occur after fresh verification.
    a.memory.plates.record_run.side_effect=lambda *args:plate.update(revision=2,location='unknown')
    with patch.object(module,'preflight',return_value=s),patch('home_hamilton_exchange.native',return_value=n), \
            patch.object(actual,'preview',return_value={'existing':'plan'}) as preview, \
            patch.object(actual,'execute',return_value={'ok':True,'record':'existing-receipt'}) as execute:
        spec=adapter.preview(plate_id,1,'HOME','Cellvis P24-1.5H-N')
        run=Mock();run.stopped.return_value=False
        assert adapter.execute_step(run,spec,'retrieve_hotel',None)['ok']
        execute.assert_called_once_with(run,backend.s,geometry['cfg'],{'existing':'plan'})
        if plate_id is None:a.memory.plates.get.assert_not_called()
        else:a.memory.plates.record_run.assert_called_once()
        backend.s.move_gripper.assert_called_once_with(7,5)
