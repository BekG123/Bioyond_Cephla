"""Integration regressions for consolidated calibration; no hardware."""
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import teach
import fast_disk
import autonomy
import mcp_teach
import sdk_pose
from pick_and_hold.Calibration import fast_disk as calibration
from robot_service import RobotService


class CalibrationModuleTests(unittest.TestCase):
    def test_compatibility_paths_share_implementations(self):
        self.assertIs(teach, calibration)
        self.assertIs(fast_disk, calibration)
        for name in ('number', 'wrap', 'near', 'ik', 'check_path',
                     'ensure_arrival', 'GuardedService', 'TransferError'):
            self.assertIs(getattr(autonomy, name), getattr(calibration, name))
        self.assertIs(mcp_teach.sdk_detect, calibration.sdk_detect)
        self.assertIs(mcp_teach.final_acc_pose, calibration.final_acc_pose)
        self.assertIs(sdk_pose.compose, calibration.compose)

    def service(self, **changes):
        state = dict(connected=True, errors=[], mode='auto', enabled=True,
                     program='running', initialized=True)
        state.update(changes)
        robot = SimpleNamespace(
            connected=state['connected'],
            get_robot_errors=lambda: state['errors'],
            get_ctrl_mode=lambda: dict(mode=state['mode']),
            get_enable_status=lambda: state['enabled'],
            get_prog_state=lambda: dict(state=state['program']),
            get_lua_app_status=lambda: state['initialized'],
            get_cartesian_pose=lambda: dict(X=.304023, Y=-.0697755, Z=.285113,
                                           Rx=0., Ry=0., Rz=math.pi / 2))
        service = RobotService.__new__(RobotService)
        service.robot = robot
        return service

    def test_pose_conversion_through_real_service_adapter(self):
        self.assertEqual(self.service().pose_mm(),
                         dict(X=304.023, Y=-69.776, Z=285.113,
                              Rx=0., Ry=0., Rz=90.))

    def test_controller_readiness_through_real_service_adapter(self):
        self.assertIsNone(self.service()._preflight())
        for changed, message in [
            (dict(connected=False), 'not connected'),
            (dict(errors=[3873]), 'active errors'),
            (dict(mode='manual'), 'manual mode'),
            (dict(enabled=False), 'disabled'),
            (dict(program='paused'), 'paused'),
            (dict(initialized=False), 'uninitialized'),
        ]:
            with self.subTest(changed=changed):
                self.assertIn(message, self.service(**changed)._preflight())


if __name__ == '__main__':
    unittest.main()
