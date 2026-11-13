"""Fake-only tests: planning never sends commands; preparation never retries."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import Mock
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hotel_squid_composition as composition
import hotel_holder_preparation as preparation
import home_hamilton_exchange as exchange
import cellvis24_workflow as workflow


@pytest.fixture
def rig(monkeypatch,tmp_path):
    _,_,g=composition.hotel(1)
    backend=Mock();backend.params.return_value=g['cfg']
    backend.s.envelope=g['envelope'];backend.s.envelope_enabled=True
    state=dict(pose_mm=deepcopy(g['home']),joints=dict(J1=100,J2=1,J3=2,J4=3))
    native=dict(moving=False,external_axes=dict(E1=.019,E2=1.947))
    for module in (composition,preparation):monkeypatch.setattr(module,'preflight',lambda s:deepcopy(state))
    for module in (exchange,preparation):monkeypatch.setattr(module,'native',lambda s:deepcopy(native))
    monkeypatch.setattr(workflow,'squid_ready',Mock(return_value={}))
    monkeypatch.setattr(preparation,'OUTPUT',tmp_path)
    monkeypatch.setattr(preparation.time,'sleep',lambda _:None)
    def jaws(target,speed):native['external_axes']['E1']=target;return dict(ok=True)
    def command(values,job,timeout):
        if job==13:backend.s.robot.get_sys_var_i.return_value={7:int(values[7]),8:250104}
        if job==14:native['external_axes']['E2']=values[9]
        return dict(ok=True)
    backend.s.move_gripper.side_effect=jaws;backend.s._hostpoint.side_effect=command
    backend.s.program.return_value=dict(ok=True)
    backend.s._locked.side_effect=lambda fn:fn()
    run=Mock(run_id='a'*32);run.stopped.return_value=False
    adapter=composition.HotelSquidAdapter(backend=backend,registry=Mock())
    return adapter,backend,state,native,run


def preview(rig):return rig[0].preview(None,1,'Squid','Cellvis P24-1.5H-N')


@pytest.mark.parametrize('angle',[1.947,90.717,181.774,-20])
def test_wrong_angle_builds_preparation_without_commands(rig,angle):
    a,b,_,n,_=rig;n['external_axes']['E2']=angle
    spec=preview(rig);a.verify(spec)
    assert a.steps(spec)[0]['id']=='prepare_home_holder'
    assert spec['holder_preparation']['target']==1.77
    assert spec['holder_preparation']['targets']==exchange.holder_restore_targets(angle,1.77)
    b.s.move_gripper.assert_not_called();b.s._hostpoint.assert_not_called()


@pytest.mark.parametrize('angle',[1.74,1.77,1.82])
def test_accepted_angle_keeps_existing_route(rig,angle):
    a,_,_,n,_=rig;n['external_axes']['E2']=angle
    spec=preview(rig)
    assert spec['holder_preparation'] is None
    assert [x['id'] for x in a.steps(spec)]==['retrieve_hotel','register_barcode','deliver_squid']


@pytest.mark.parametrize('angle',[float('nan'),float('inf'),361])
def test_invalid_angle_is_not_repaired(rig,angle):
    rig[3]['external_axes']['E2']=angle
    with pytest.raises(Exception,match='finite'):preview(rig)


def test_wrong_pose_and_moving_have_specific_blockers(rig):
    rig[2]['pose_mm']['Z']-=1
    with pytest.raises(Exception,match='outside HOME clearance'):preview(rig)
    rig[2]['pose_mm']['Z']+=1;rig[3]['moving']=True
    with pytest.raises(Exception,match='Arm is moving'):preview(rig)


def test_open_then_restore_then_existing_retrieval(rig,monkeypatch):
    a,b,_,n,run=rig;spec=preview(rig)
    prior=a.execute_step(run,spec,'prepare_home_holder',None)
    assert n['external_axes']==dict(E1=28,E2=1.77)
    assert b.s._hostpoint.call_args_list[-1].args[1]==14
    module,_,_=composition.hotel(1)
    monkeypatch.setattr(module,'preview',Mock(return_value={'checked':True}))
    executor=Mock(return_value=dict(ok=True,record='retrieval'))
    monkeypatch.setattr(module,'execute',executor)
    result=a.execute_step(run,spec,'retrieve_hotel',prior)
    assert result['record']=='retrieval'
    assert [c.args[0] for c in b.s.move_gripper.call_args_list]==[28,7]
    executor.assert_called_once()
    assert executor.call_args.kwargs=={'restore_holder_for_handoff':True}
    with pytest.raises(FileExistsError):preparation.execute(run,b,spec,a.require)


def test_reported_home_offset_survives_holder_preparation_and_retrieval_handoff(rig,monkeypatch):
    a,b,s,n,run=rig
    s['pose_mm'].update(X=312.073,Y=-66.385,Z=105.69,Rz=89.698)
    spec=preview(rig);a.verify(spec)
    prior=a.execute_step(run,spec,'prepare_home_holder',None)
    module,_,_=composition.hotel(1)
    monkeypatch.setattr(module,'preview',Mock(return_value={'checked':True}))
    executor=Mock(return_value=dict(ok=True,record='retrieval'))
    monkeypatch.setattr(module,'execute',executor)
    a.execute_step(run,spec,'retrieve_hotel',prior)
    executor.assert_called_once()
    b.s.move_cartesian.assert_not_called()


@pytest.mark.parametrize('key,value',[('X',float('nan')),('Y',float('inf')),('Rz',float('nan'))])
def test_invalid_home_feedback_refused(rig,key,value):
    rig[2]['pose_mm'][key]=value
    with pytest.raises(Exception,match='finite measured pose'):preview(rig)


def test_changed_holder_or_changed_preparation_requires_new_plan(rig):
    a,_,_,n,_=rig;spec=preview(rig)
    spec['holder_preparation']['targets']=[5]
    with pytest.raises(Exception,match='preparation changed'):a.verify(spec)
    spec=preview(rig);n['external_axes']['E2']+=1
    with pytest.raises(Exception,match='Starting configuration changed'):a.verify(spec)


@pytest.mark.parametrize('failure',['timeout','wrong_arrival','jaw_failed','stop_after_probe'])
def test_failed_preparation_stops_before_retrieval_without_retry(rig,failure):
    a,b,_,n,run=rig;spec=preview(rig)
    original=b.s._hostpoint.side_effect
    def command(values,job,timeout):
        if job==14:
            if failure=='timeout':raise TimeoutError('unknown physical state')
            if failure=='wrong_arrival':return dict(ok=True)
        result=original(values,job,timeout)
        if job==13 and failure=='stop_after_probe':run.stopped.return_value=True
        return result
    b.s._hostpoint.side_effect=command
    if failure=='jaw_failed':b.s.move_gripper.side_effect=lambda *args:dict(ok=True)
    with pytest.raises(Exception):a.execute_step(run,spec,'prepare_home_holder',None)
    calls=[c for c in b.s._hostpoint.call_args_list if c.args[1]==14]
    assert len(calls)==(1 if failure in ('timeout','wrong_arrival') else 0)
    assert not any(c.args[0]==7 for c in b.s.move_gripper.call_args_list)
    data=json.loads((preparation.OUTPUT/(run.run_id+'.json')).read_text())
    assert data['status']=='stopped_or_uncertain'
    with pytest.raises(Exception,match='receipt required'):a.execute_step(run,spec,'retrieve_hotel',None)


def test_preparation_result_cannot_authorize_changed_start(rig):
    a,_,s,_,run=rig;spec=preview(rig)
    result=a.execute_step(run,spec,'prepare_home_holder',None)
    s['pose_mm']['Z']-=1
    with pytest.raises(Exception,match='outside HOME clearance'):a.execute_step(run,spec,'retrieve_hotel',result)
