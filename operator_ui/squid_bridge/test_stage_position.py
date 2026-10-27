"""Native loading delegate checks with a fake microscope, no hardware."""
from pathlib import Path
from types import SimpleNamespace as NS
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,os.getcwd())
os.environ['QT_API']='pyqt5'
import control._def as config
import stage_position


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        path=Path(self.tmp.name)/'ref.json'
        self.target=dict(x_mm=.05,y_mm=.05,z_mm=1.05)
        path.write_text(json.dumps(dict(operator_confirmed=True,controller_serial='12769210',dropoff=self.target)))
        for p in (patch.object(stage_position,'REFERENCE',path),
                  patch.object(config,'CONTROLLER_SN','12769210'),
                  patch.object(config,'SIMULATE_MICROCONTROLLER',False)):
            p.start();self.addCleanup(p.stop)
        self.stage=Mock()
        self.stage.get_config.return_value=NS(X_AXIS=NS(MIN_POSITION=5,MAX_POSITION=115),
            Y_AXIS=NS(MIN_POSITION=4,MAX_POSITION=76),Z_AXIS=NS(MIN_POSITION=.05,MAX_POSITION=6))
        self.server=NS(microscope=NS(stage=self.stage),_commands={},
            _cmd_get_acquisition_status=Mock(return_value={'in_progress':False}),
            _cmd_get_position=Mock(return_value=self.target))
        self.native=Mock()
        p=patch('squid.stage.utils.move_to_loading_position',self.native);p.start();self.addCleanup(p.stop)
        stage_position.install(self.server)
        self.hash=stage_position.reference()[1]
        self.move=self.server._commands['return_to_recorded_dropoff']
        self.original=(config.SLIDE_POSITION.LOADING_X_MM,config.SLIDE_POSITION.LOADING_Y_MM)

    def test_native_loading_with_reviewed_target_restores_config_and_limits(self):
        def inspect(*a,**kw):
            self.assertEqual((config.SLIDE_POSITION.LOADING_X_MM,config.SLIDE_POSITION.LOADING_Y_MM),(.05,.05))
        self.native.side_effect=inspect
        self.assertTrue(self.move(self.hash)['at_dropoff'])
        self.native.assert_called_once_with(self.stage,blocking=True,is_wellplate=True)
        self.assertEqual((config.SLIDE_POSITION.LOADING_X_MM,config.SLIDE_POSITION.LOADING_Y_MM),self.original)
        self.stage.set_limits.assert_called_once_with(x_pos_mm=115,x_neg_mm=5,y_pos_mm=76,y_neg_mm=4)
        self.stage.move_z_to.assert_called_once_with(1.05,blocking=True)

    def test_failure_restores_limits_without_retry_or_z_raise(self):
        self.native.side_effect=TimeoutError('uncertain')
        with self.assertRaises(TimeoutError):self.move(self.hash)
        self.assertEqual(self.native.call_count,1)
        self.stage.set_limits.assert_called_once()
        self.stage.move_z_to.assert_not_called()
        self.assertEqual((config.SLIDE_POSITION.LOADING_X_MM,config.SLIDE_POSITION.LOADING_Y_MM),self.original)

    def test_scan_and_wrong_reference_refuse_before_motion(self):
        with self.assertRaises(ValueError):self.move('wrong')
        self.server._cmd_get_acquisition_status.return_value={'in_progress':True}
        with self.assertRaises(RuntimeError):self.move(self.hash)
        self.native.assert_not_called()

    def test_info_is_readonly(self):
        result=self.server._commands['get_stage_reference']()
        self.assertEqual(result['dropoff'],self.target)
        self.assertFalse(result['stage_simulated'])
        self.native.assert_not_called()

    def test_negative_target_fails_before_retraction_or_limits_change(self):
        data,fingerprint=stage_position.reference()
        data['dropoff']['x_mm']=-.05000625
        stage_position.REFERENCE.write_text(json.dumps(data))
        fingerprint=stage_position.reference()[1]
        with self.assertRaisesRegex(ValueError,'Negative loading'):self.move(fingerprint)
        self.native.assert_not_called()
        self.stage.set_limits.assert_not_called()
        self.stage.move_z_to.assert_not_called()


if __name__=='__main__':unittest.main()
