"""Legacy entry point stays retired; native feedback still supports protection."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sequences import Runner
from pick_and_hold.Grip.motion import seq_grip


class GripTests(unittest.TestCase):
    def test_legacy_parameters_cannot_restore_automatic_closing(self):
        for params in ({}, {'coarse_speed':137}, {'floor':3,'reopen_on_miss':False}):
            service=Mock();run=Runner();run.state='running'
            result=seq_grip(run,service,params)
            self.assertFalse(result['ok'])
            self.assertTrue(result['grip_unavailable'])
            self.assertEqual(run.state,'error')
            self.assertEqual(service.mock_calls,[])

    def test_service_reads_all_torques_from_completed_move(self):
        from robot_service import RobotService
        service=RobotService();service.robot=Mock()
        service.robot.get_sys_var_i.return_value={10:9500,11:90000,12:100,13:400,14:5,15:10,16:90}
        report=service._read_gripper_report()
        self.assertEqual(report['joints']['J4'],90)
        self.assertTrue(report['telemetry_live'])
        service.robot.get_sys_var_i.assert_called_once_with(list(range(10,17)))


if __name__=='__main__':unittest.main()
