import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robot_service import RobotService


class ControllerTests(unittest.TestCase):
    def service(self):
        svc = Mock()
        svc._locked.side_effect = lambda fn: fn()
        svc._preflight.return_value = None
        svc._endpoint_addr.return_value = ('unused', 0)
        svc._hostpoint.return_value = {'ok': True}
        svc.robot.get_sys_var_i.return_value = {7: 124, 8: 250101}
        svc.pose_mm.return_value = dict(X=1, Y=2, Z=3, Rz=4)
        return svc

    def state(self, e2=2.1, e1=28):
        return dict(error=False, emergency=False, moving=False, drag=False,
                    manual=False, enabled=True, external_axes={'E1': e1, 'E2': e2},
                    external_units={'E1': 'mm', 'E2': 'degrees'})

    def test_unsupported_controller_never_gets_motion_command(self):
        svc = self.service()
        svc.robot.get_sys_var_i.return_value = {7: 0, 8: 0}
        with patch('draggo.DragGoRPC') as rpc, patch('secrets.randbelow', return_value=123):
            rpc.return_value.info.return_value = self.state()
            self.assertFalse(RobotService.position_calibration_e2(svc)['ok'])
        self.assertEqual([c.args[1] for c in svc._hostpoint.call_args_list], [7])

    def test_verified_correction_preserves_other_axes(self):
        for e1, ok in [(28, True), (27, False)]:
            svc = self.service()
            with patch('draggo.DragGoRPC') as rpc, patch('secrets.randbelow', return_value=123):
                rpc.return_value.info.side_effect = [self.state(), self.state(1.82, e1)]
                self.assertEqual(RobotService.position_calibration_e2(svc)['ok'], ok)
            self.assertEqual([c.args[1] for c in svc._hostpoint.call_args_list], [7, 8])

    def test_bound_refusal_sends_no_job(self):
        svc = self.service()
        with patch('draggo.DragGoRPC') as rpc:
            rpc.return_value.info.return_value = self.state(10)
            self.assertFalse(RobotService.position_calibration_e2(svc)['ok'])
        svc._hostpoint.assert_not_called()

    def test_previous_displayed_minimum_is_accepted(self):
        svc = self.service()
        with patch('draggo.DragGoRPC') as rpc, patch('secrets.randbelow', return_value=123):
            rpc.return_value.info.side_effect = [self.state(), self.state(1.7699)]
            result = RobotService.position_calibration_e2(svc)
        self.assertTrue(result['ok'])

    def test_arrival_uses_approved_band_with_unchanged_motion_command(self):
        for value, expected in [(1.740, True), (1.749324037839865, True), (1.750, True), (1.7575638072998392, True), (1.760, True), (1.7658034700381073, True),
                                (1.739999, False), (1.820001, False)]:
            with self.subTest(value=value):
                svc = self.service()
                with patch('draggo.DragGoRPC') as rpc, patch('secrets.randbelow', return_value=123):
                    rpc.return_value.info.side_effect = [self.state(), self.state(value)]
                    self.assertEqual(RobotService.position_calibration_e2(svc)['ok'], expected)
                self.assertEqual([c.args[1] for c in svc._hostpoint.call_args_list], [7, 8])


if __name__ == '__main__':
    unittest.main()
