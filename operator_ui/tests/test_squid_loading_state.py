"""Loading completion and identity tests; no microscope commands."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS,ModuleType
from unittest.mock import Mock
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from squid_bridge.loading_state import LoadingState,controller_identity
from squid_loading import at_loading

TARGET=dict(x_mm=.5000625,y_mm=.5000625,z_mm=.063984375)
NATIVE=dict(x_mm=.5,y_mm=.5,z_mm=.1)


def bridge(tracker,actual=NATIVE,serial='12769210',fingerprint='ref',busy=False):
    return dict(controller_serial=serial,stage_simulated=False,reference_hash=fingerprint,
                loading=tracker.snapshot(actual,TARGET,serial,fingerprint,busy))


def completed():
    tracker=LoadingState();tracker.completed(True,NATIVE,'12769210','ref');return tracker


def test_successful_native_load_accepts_036mm_z_difference():
    assert at_loading(NATIVE,TARGET,bridge(completed()),'12769210')['at_dropoff']


@pytest.mark.parametrize('success',[False,None,0])
def test_gui_flag_or_failed_callback_is_not_completion(success):
    tracker=LoadingState();tracker.completed(success,NATIVE,'12769210','ref','failed')
    with pytest.raises(Exception,match='successful loading'):at_loading(NATIVE,TARGET,bridge(tracker),'12769210')


def test_coordinates_alone_do_not_prove_loaded():
    with pytest.raises(Exception):at_loading(NATIVE,TARGET,bridge(LoadingState()),'12769210')


@pytest.mark.parametrize('axis,value',[('x_mm',.53),('y_mm',.53),('z_mm',.12),('z_mm',float('nan'))])
def test_stage_drift_invalidates_until_another_successful_load(axis,value):
    tracker=completed();actual=dict(NATIVE,**{axis:value})
    assert bridge(tracker,actual)['loading']['at_dropoff'] is False
    assert bridge(tracker)['loading']['at_dropoff'] is False


def test_busy_temporarily_blocks_but_does_not_invalidate_stationary_completion():
    tracker=completed()
    assert not bridge(tracker,busy=True)['loading']['at_dropoff']
    assert bridge(tracker)['loading']['at_dropoff']


def test_new_session_or_changed_controller_or_reference_cannot_reuse_completion():
    for values in [dict(serial='OTHER'),dict(serial=None),dict(fingerprint='changed')]:
        assert not bridge(completed(),**values)['loading']['at_dropoff']
    assert not bridge(LoadingState())['loading']['at_dropoff']
    response=bridge(completed());response['loading']['receipt']['session_id']='old'
    with pytest.raises(Exception):at_loading(NATIVE,TARGET,response,'12769210')


def test_actual_open_device_identity_does_not_need_launch_override():
    handle=NS(port='COM4',is_open=True)
    microscope=NS(low_level_drivers=NS(microcontroller=NS(_serial=NS(_serial=handle))))
    ports=[NS(device='COM9',serial_number='wrong'),NS(device='COM4',serial_number='12769210')]
    assert controller_identity(microscope,ports)=='12769210'
    handle.is_open=False
    assert controller_identity(microscope,ports) is None


def test_general_position_checks_remain_strict():
    from squid_execution import at_position
    with pytest.raises(Exception):at_position(NATIVE,TARGET)


def test_bridge_wraps_gui_success_and_invalidates_stage_moves(tmp_path,monkeypatch):
    from squid_bridge import stage_position
    config=NS(CONTROLLER_SN=None,SIMULATE_MICROCONTROLLER=False,SLIDE_POSITION=NS(LOADING_X_MM=.5,LOADING_Y_MM=.5))
    control=ModuleType('control');control._def=config
    monkeypatch.setitem(sys.modules,'control',control);monkeypatch.setitem(sys.modules,'control._def',config)
    utils=ModuleType('squid.stage.utils');utils.move_to_loading_position=Mock()
    monkeypatch.setitem(sys.modules,'squid.stage.utils',utils)
    from serial.tools import list_ports
    monkeypatch.setattr(list_ports,'comports',lambda:[NS(device='COM4',serial_number='12769210')])
    ref=tmp_path/'reference.json';ref.write_text(json.dumps(dict(operator_confirmed=True,controller_serial='12769210',dropoff=TARGET)))
    monkeypatch.setattr(stage_position,'REFERENCE',ref)
    get_config=lambda:NS(**{axis+'_AXIS':NS(MIN_POSITION=0,MAX_POSITION=120) for axis in ('X','Y','Z')})
    move=Mock();stage=NS(get_config=get_config,move_x_to=move,move_z_to=Mock(),set_limits=Mock())
    mcu=NS(_serial=NS(_serial=NS(port='COM4',is_open=True)),is_busy=lambda:False)
    callback=Mock();widget=NS(_callback_loading_position_reached=callback,
        signal_threaded_stage_move_started=Mock(),signal_scanning_position_reached=Mock())
    server=NS(gui=NS(stageUtils=widget),microscope=NS(stage=stage,low_level_drivers=NS(microcontroller=mcu)),
        _commands={},_cmd_get_position=lambda:dict(NATIVE),_cmd_get_acquisition_status=lambda:dict(in_progress=False))
    stage_position.install(server)
    info=server._commands['get_stage_reference']
    assert info()['controller_serial']=='12769210' and not info()['loading']['at_dropoff']
    widget._callback_loading_position_reached(False,'jam')
    assert info()['loading']['status']=='failed'
    widget._callback_loading_position_reached(True,None)
    assert info()['loading']['at_dropoff']
    stage.move_x_to(20)
    move.assert_called_once_with(20)
    assert not info()['loading']['at_dropoff']
    callback.assert_any_call(False,'jam')


def test_cellvis_gate_uses_success_receipt_and_device_binding(monkeypatch):
    import cellvis24_squid_route as route
    from squid_stage import REFERENCE
    from squid_execution import digest
    ref=json.loads(REFERENCE.read_bytes());fingerprint=digest(ref)
    tracker=LoadingState();tracker.completed(True,NATIVE,ref['controller_serial'],fingerprint)
    info=bridge(tracker,fingerprint=fingerprint)
    adapter=Mock();adapter.connect.return_value=dict(stage_simulated=False,status='idle')
    monkeypatch.setattr(route,'SquidAdapter',lambda **kw:adapter)
    monkeypatch.setattr(route,'native_command',lambda command:dict(NATIVE) if command=='get_position' else info)
    assert route.instrument_ready(dict(squid_loading_position=TARGET))==NATIVE
    info['controller_serial']='wrong'
    with pytest.raises(Exception,match='controller'):route.instrument_ready(dict(squid_loading_position=TARGET))
