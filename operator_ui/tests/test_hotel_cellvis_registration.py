"""Offline receipt/dispatch integration; every hardware boundary is faked."""
import json
import time
import sys
from pathlib import Path
from unittest.mock import Mock
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hotel_cellvis_handoff as handoff
import composed_cellvis_registration as registration
from hotel_squid_composition import hotel,profile_binding,HotelSquidAdapter


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value));return path


def test_real_accepted_scanner_and_delivery_geometry():
    ref=handoff.scanner_reference()
    assert ref['scanner_z']==163.76
    assert ref['geometry']['id']=='6b66922bf37445cfbdc94711ac8f9b54'
    steps=registration.delivery_steps()
    assert steps[-1]['label']=='Empty HOME clearance'
    assert not any(s['label']=='Check destination before retrieval' for s in steps)
    assert any(s['kind']=='jaws' and s['target']==7 for s in steps)


def fresh_handoff(tmp_path,monkeypatch):
    module,_,g=hotel(1)
    monkeypatch.setattr(module,'OUTPUT',tmp_path/'retrievals')
    monkeypatch.setattr(handoff,'FOLDER',tmp_path/'handoffs')
    source=write(module.OUTPUT/'retrieval.json',dict(
        status='completed_retrieval_HOME_released_operator_observation_pending',
        plan=dict(geometry=g),final=dict(pose_mm=g['home']),
        final_native=dict(external_axes=dict(E1=28,E2=1.77)),finished_at=time.time()))
    path=handoff.create(source,profile_binding('Cellvis P24-1.5H-N',1),handoff.scanner_reference())
    return source,path


def test_fresh_hotel_receipt_enters_existing_source_validator(tmp_path,monkeypatch):
    from cellvis24_workflow import source_record
    source,path=fresh_handoff(tmp_path,monkeypatch)
    actual,record=source_record(path)
    assert actual==path.resolve() and record['payload']=='empty'
    assert 'not inferred' in record['operator_observation']
    with pytest.raises(FileExistsError):
        handoff.create(source,record['profile_binding'],record['reference'])
    d=json.loads(source.read_text());d['finished_at']-=1900;write(source,d)
    with pytest.raises(Exception,match='expired'):source_record(path)


def test_changed_hotel_receipt_cannot_be_reused(tmp_path,monkeypatch):
    source,path=fresh_handoff(tmp_path,monkeypatch)
    d=json.loads(source.read_text());d['extra']='changed';write(source,d)
    with pytest.raises(Exception,match='changed'):
        handoff.validate_source(path,json.loads(path.read_text()))


def scan_harness(tmp_path,monkeypatch,results,expected=None):
    _,source=fresh_handoff(tmp_path,monkeypatch)
    run=Mock();run.stopped.return_value=False
    monkeypatch.setattr(registration,'preflight',lambda s:{})
    monkeypatch.setattr(registration.time,'sleep',lambda n:None)
    registry=Mock();registry.get.return_value=dict(metadata={})
    presented=[];returned=[];scans=[]
    def present(current,angle):presented.append(angle);return tmp_path/f'pickup_{angle}.json'
    def scan():
        value=results[len(scans)];scans.append(value)
        path=write(tmp_path/f'scan{len(scans)}.json',value)
        return value,path
    def back(held):
        returned.append(held)
        return write(tmp_path/f'home{len(returned)}.json',dict(status='completed'))
    def execute():return registration.register(run,Mock(),source,expected,registry,
        present=present,scan=scan,return_home=back)
    return execute,presented,returned,scans,source,registry


DECODE=dict(result='decoded',barcode='ACTUAL',plate_registry=dict(saved=True,plate_id='ACTUAL'))


def test_registration_uses_new_identity_then_returns_home(tmp_path,monkeypatch):
    execute,presented,returned,scans,source,registry=scan_harness(tmp_path,monkeypatch,[DECODE])
    result=execute()
    assert result['plate_id']=='ACTUAL' and presented==[1.77] and len(returned)==1
    record=json.loads(Path(result['record']).read_text())
    assert record['status']=='registered_HOME_released' and 'contents' not in record
    with pytest.raises(FileExistsError):execute()
    assert len(scans)==1


def test_composed_default_pickup_explicitly_plans_live_holder_centering(tmp_path,monkeypatch):
    import barcode_opposite_side_trial as trial
    import barcode_opposite_pickup as pickup
    import barcode_opposite_transport as transport
    _,source=fresh_handoff(tmp_path,monkeypatch)
    run=Mock();run.stopped.return_value=False;backend=Mock();backend.params.return_value={}
    monkeypatch.setattr(registration,'preflight',lambda service:{})
    planner=Mock(return_value={'checked':True});monkeypatch.setattr(trial,'plan',planner)
    monkeypatch.setattr(trial,'execute',Mock(return_value=dict(ok=True,record='checked-trial')))
    held=tmp_path/'held.json';monkeypatch.setattr(pickup,'run',Mock(return_value=held))
    monkeypatch.setattr(transport,'plan',Mock(return_value={}))
    monkeypatch.setattr(transport,'execute',Mock(return_value=dict(ok=True)))
    scan_path=write(tmp_path/'scan.json',DECODE)
    home=write(tmp_path/'release_restore.json',dict(status='completed'))
    registry=Mock();registry.get.return_value=dict(metadata={})
    result=registration.register(run,backend,source,None,registry,
        scan=lambda:(DECODE,scan_path),return_home=lambda value:home)
    assert result['plate_id']=='ACTUAL'
    planner.assert_called_once_with(backend.s,{},source.resolve(),1.77,prepare_original=True)


def test_five_no_reads_use_other_side_only_once(tmp_path,monkeypatch):
    execute,presented,returned,scans,_,_=scan_harness(tmp_path,monkeypatch,[dict(result='no_read')]*5+[DECODE])
    assert execute()['ok']
    assert presented==[1.77,181.77] and len(scans)==6 and len(returned)==2


@pytest.mark.parametrize('failure',[dict(result='timeout'),dict(result='transport_error'),
    dict(result='decoded',plate_registry=dict(saved=False)),dict(DECODE,stop_error='stop failed')])
def test_uncertain_scan_never_retries_or_moves_away(tmp_path,monkeypatch,failure):
    execute,presented,returned,scans,_,_=scan_harness(tmp_path,monkeypatch,[failure])
    with pytest.raises(Exception):execute()
    assert len(scans)==1 and not returned and presented==[1.77]


def test_no_read_both_sides_returns_home_and_blocks(tmp_path,monkeypatch):
    execute,presented,returned,scans,_,_=scan_harness(tmp_path,monkeypatch,[dict(result='no_read')]*10)
    with pytest.raises(Exception,match='returned to HOME'):execute()
    assert len(scans)==10 and len(returned)==2


def test_wrong_identity_blocks_station_delivery(tmp_path,monkeypatch):
    execute,_,returned,scans,_,registry=scan_harness(tmp_path,monkeypatch,[DECODE],expected='OTHER')
    with pytest.raises(Exception,match='identity differs'):execute()
    assert len(scans)==1 and not returned
    registry.record_run.assert_called_once()


def test_shared_service_pickup_transport_has_no_startup_or_extra_connection():
    run=Mock();run.stopped.return_value=False;backend=Mock()
    backend.s.envelope={'X':[200,450],'Y':[-250,380],'Z':[70,400]}
    host=registration.PickupHost(backend,run)
    host.call('gripper',dict(action='move',e1=3.9,speed=5))
    backend.s.move_gripper.assert_called_once_with(3.9,5)
    for path,body in [('connect',{}),('program',{'action':'start'}),('clear_errors',{})]:
        with pytest.raises(Exception,match='Unsupported'):host.call(path,body)
    run.stopped.return_value=True
    with pytest.raises(Exception,match='stopped'):host.call('move',{})
    host.call('program',{'action':'stop'})
    backend.s.program.assert_called_once_with('stop')


@pytest.mark.parametrize('direct', [False, True])
def test_station_delivery_reuses_existing_executor_and_exact_slice(tmp_path,monkeypatch,direct):
    import cellvis24_workflow as workflow
    scan=write(tmp_path/'scan.json',DECODE);home=write(tmp_path/'home.json',{})
    record=write(tmp_path/'registration.json',dict(status='registered_HOME_released',plate_id='ACTUAL',
        scan_receipt=str(scan),scan_sha256=handoff.sha(scan),home_receipt=str(home),home_sha256=handoff.sha(home),finished_at=time.time()))
    plan=Mock(return_value=dict(id='a'*32));execute=Mock(return_value=dict(ok=True,record='delivery'))
    monkeypatch.setattr(workflow,'plan',plan);monkeypatch.setattr(workflow,'execute_checked_steps',execute)
    monkeypatch.setattr(workflow,'validate_steps',Mock());monkeypatch.setattr(registration,'preflight',Mock())
    steps=registration.delivery_steps();backend=Mock();run=Mock()
    checker=Mock()
    options={'station_check':checker} if direct else {}
    result=registration.deliver(run,backend,dict(record=str(record),plate_id='ACTUAL',home_receipt=str(home)),steps,**options)
    assert result['plate_location']=='Squid'
    assert execute.call_args.args[3]['steps']==steps
    assert execute.call_args.kwargs['ends_held'] is False
    if direct:
        assert plan.call_args.kwargs['station_check'] is checker
        assert execute.call_args.kwargs['station_check'] is checker
    else:
        assert 'station_check' not in plan.call_args.kwargs
        assert 'station_check' not in execute.call_args.kwargs
    write(scan,dict(DECODE,barcode='changed'))
    with pytest.raises(Exception,match='registration'):
        registration.deliver(run,backend,dict(record=str(record),plate_id='ACTUAL',home_receipt=str(home)),steps)
    execute.assert_called_once()


def test_actual_pickup_core_uses_host_service_for_closure_and_proof_lift(tmp_path,monkeypatch):
    import barcode_opposite_pickup as pickup
    source=write(tmp_path/'run.json',{})
    pose=dict(X=313.03,Y=-65.92,Z=75.72,Rz=90.07)
    g=dict(seat=dict(pose),cfg={})
    backend=Mock();run=Mock();run.stopped.return_value=False
    backend.params.return_value={};backend.s.envelope_enabled=True
    backend.s.envelope={'X':[200,450],'Y':[-250,380],'Z':[70,400]}
    axes=dict(E1=28,E2=1.77)
    backend.s.status.side_effect=lambda:dict(connected=True,errors=[],enabled=True,
        control_mode=dict(mode='auto'),program_state=dict(state='running'),lua_app_initialized=True,
        pose_mm=dict(pose),joints={})
    host=registration.PickupHost(backend,run)
    host.native=lambda:dict(moving=False,error=False,emergency=False,drag=False,manual=False,external_axes=dict(axes))
    def grip(target,speed):axes['E1']=target;return dict(ok=True)
    backend.s.move_gripper.side_effect=grip
    backend.s.torque_report.side_effect=lambda:dict(ok=True,telemetry_live=True,e1_torque=10,e1_position=axes['E1'])
    def move(**body):pose['Z']=body['z'];return dict(ok=True)
    backend.s.move_cartesian.side_effect=move
    monkeypatch.setattr(pickup,'source_data',lambda s:(source,dict(plan=dict(target=1.77)),g))
    monkeypatch.setattr(pickup,'check_path',Mock());monkeypatch.setattr(pickup.time,'sleep',lambda n:None)
    cli=Mock(side_effect=AssertionError('No HTTP/self-dispatch or extra native connection'))
    monkeypatch.setattr(pickup,'api',cli);monkeypatch.setattr(pickup,'DragGoRPC',cli)
    result=pickup.run(source,host=host)
    expected=pickup.closure_plan(28,3.9)['commands']
    assert backend.s.move_gripper.call_args_list==[
        __import__('unittest.mock',fromlist=['call']).call(c['target_e1_mm'],c['speed']) for c in expected]
    assert expected[-1]['speed']==5
    backend.s.move_cartesian.assert_called_once_with(x=313.03,y=-65.92,z=80.72,rz=90.07,speed=5,interpolation='linear')
    record=json.loads(result.read_text())
    assert record['status']=='proof_lift_completed_retention_pending'
    assert 'not asserted' in record['alignment_observation']
    cli.assert_not_called()


def test_real_adapter_previews_complete_chain_without_motion(monkeypatch):
    import hotel_squid_composition as adapter_module
    import cellvis24_workflow as workflow
    import home_hamilton_exchange as exchange
    _,_,geometry=hotel(1)
    agent=Mock();backend=agent.backend
    backend.params.return_value=geometry['cfg'];backend.s.envelope=geometry['envelope']
    s=dict(pose_mm=geometry['home'],joints=dict(J1=100,J2=1,J3=2,J4=3))
    monkeypatch.setattr(adapter_module,'preflight',lambda service:s)
    monkeypatch.setattr(exchange,'native',lambda service:dict(moving=False,external_axes=dict(E1=28,E2=1.77)))
    monkeypatch.setattr(workflow,'squid_ready',Mock(return_value={}))
    adapter=HotelSquidAdapter(agent)
    spec=adapter.preview(None,1,'Squid','Cellvis P24-1.5H-N')
    adapter.verify(spec)
    assert [s['id'] for s in adapter.steps(spec)]==['retrieve_hotel','register_barcode','deliver_squid']
    assert spec['continuation']['scanner']['scanner_z']==163.76
    backend.s.move_gripper.assert_not_called();backend.s.move_cartesian.assert_not_called()


def test_full_composition_carries_scanned_identity_and_stops_on_failed_step(tmp_path):
    from test_lacry_workflow_composition import agent
    from lacry_workflow_composition import WorkflowComposition,composition_outline
    a=agent();adapter=Mock();spec=dict(plate_id=None,plate_profile='Cellvis P24-1.5H-N',slot=1,destination='Squid')
    adapter.preview.return_value=spec;adapter.steps.return_value=composition_outline(spec['plate_profile'],1,'Squid')[0]
    adapter.require.side_effect=HotelSquidAdapter.require
    receipts=[dict(ok=True,record='hotel'),dict(ok=True,record='scan',plate_id='ACTUAL'),dict(ok=True,record='squid',plate_id='ACTUAL')]
    adapter.execute_step.side_effect=receipts
    api=WorkflowComposition(a,adapter,tmp_path);api.propose(spec['plate_profile'],1,'Squid')
    run=Mock();run.stopped.return_value=False
    result=api.execute(run,a.pending,tmp_path/'run.json')
    assert result['ok']
    calls=adapter.execute_step.call_args_list
    assert [c.args[2] for c in calls]==['retrieve_hotel','register_barcode','deliver_squid']
    assert calls[1].args[3]==receipts[0] and calls[2].args[3]==receipts[1]
    adapter.registry.return_value.record_run.assert_called_once_with('ACTUAL',a.pending['id'],'completed',str(tmp_path/'run.json'))
