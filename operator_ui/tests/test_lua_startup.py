"""Offline readiness/timeout regression tests; never connect hardware."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from robot_service import RobotService, RobotError


class Clock:
    def __init__(self):self.t=0.
    def monotonic(self):return self.t
    def sleep(self,dt):self.t+=dt


class Tests(unittest.TestCase):
    def test_held_object_refusal_proves_no_program_command_sent(self):
        from researcher_workflow import PlateTeaching
        from home_attempts import ProgramStartRefused
        s = self.make()
        s.last_gripper = dict(e1_position=3.695, e1_torque=-111.735)
        result = s._safe_start(False)
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'gripper_held_start_refused')
        self.assertIs(result['program_start_sent'], False)
        self.assertEqual(s.robot.mock_calls, [])
        with self.assertRaises(ProgramStartRefused):
            PlateTeaching._checked(result)

    def make(self):
        s=RobotService.__new__(RobotService)
        s.last_gripper=None
        s.robot=Mock()
        s.robot.get_prog_state.return_value={'state':'running'}
        s.robot.get_lua_app_status.return_value=True
        s.robot.get_robot_errors.return_value=[]
        s.robot.prog_start.return_value='CmdDone'
        s.robot.prog_stop.return_value='CmdDone'
        return s

    def test_old_true_flag_is_not_immediate_readiness(self):
        s=self.make();c=Clock()
        with patch('robot_service.time',c):s._wait_lua_ready()
        self.assertGreaterEqual(c.t,.5)

    def test_initialization_dip_restarts_stability_window(self):
        s=self.make();c=Clock()
        s.robot.get_lua_app_status.side_effect=lambda:not .2<=c.t<.4
        with patch('robot_service.time',c):s._wait_lua_ready()
        self.assertGreaterEqual(c.t,.9)

    def test_stopped_with_true_flag_times_out(self):
        s=self.make();c=Clock();s.robot.get_prog_state.return_value={'state':'stopped'}
        with patch('robot_service.time',c),self.assertRaises(RobotError):s._wait_lua_ready()

    def test_startup_fault_is_not_cleared(self):
        s=self.make();s.robot.get_robot_errors.return_value=[{'errCode':3604}]
        with self.assertRaises(RobotError):s._wait_lua_ready()
        s.robot.clear_errors.assert_not_called()

    def test_missing_report_returns_failure_and_stops_without_retry(self):
        s=self.make();s.robot.get_prog_state.return_value={'state':'stopped'}
        s._wait_lua_ready=Mock()
        s.torque_report=Mock(return_value={'ok':False,'error':'completion timeout'})
        result=s._safe_start(False)
        self.assertFalse(result['ok']);self.assertEqual(result['stage'],'startup_torque_report')
        s.torque_report.assert_called_once();s.robot.prog_start.assert_called_once()
        s.robot.prog_stop.assert_called_once();s.robot.set_enable.assert_not_called()

    def test_readiness_timeout_never_dispatches_report(self):
        s=self.make();s.robot.get_prog_state.return_value={'state':'stopped'}
        s._wait_lua_ready=Mock(side_effect=RobotError('not ready'));s.torque_report=Mock()
        self.assertFalse(s._safe_start(False)['ok'])
        s.torque_report.assert_not_called();s.robot.prog_stop.assert_called_once()

    def test_fresh_report_retains_success(self):
        s=self.make();s.robot.get_prog_state.return_value={'state':'stopped'}
        s._wait_lua_ready=Mock();s.torque_report=Mock(return_value={'ok':True,'e1_position':0.,'e1_torque':2.})
        result=s._safe_start(False)
        self.assertTrue(result['ok']);s.robot.prog_stop.assert_not_called()

    def test_diagnostic_is_read_only_and_labels_cached_torque(self):
        s=self.make();s._locked=lambda fn:fn();s.robot.unsolicited=[{'id':1,'reply':'late'}]
        s.robot.get_sys_var_i.return_value={10:3800}
        result=s.lua_diagnostics()
        self.assertFalse(result['torque_snapshot_fresh'])
        calls={call[0] for call in s.robot.method_calls}
        self.assertEqual(calls,{'get_prog_state','get_lua_app_status','get_robot_errors','get_sys_var_i'})


if __name__=='__main__':unittest.main()
