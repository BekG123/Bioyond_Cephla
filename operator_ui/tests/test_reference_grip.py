"""Continuous Grip commissioning checks, fake hardware only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sequences import Runner
from researcher_teaching import TeachingError
from pick_and_hold.Grip.reference_grip import ReferenceGrip, configuration
from test_position_grip import Service


class FakeService(Service):
    def __init__(self):
        super().__init__()
        del self.program
    def status(self):
        result=super().status()
        result['program_state']['state']='running'
        return result
    def _preflight(self):
        return None
    def torque_report(self):
        return dict(ok=True, telemetry_live=True, e1_position=self.e1, e1_torque=95,
                    joints={'J1':1,'J2':1,'J3':1,'J4':1})
    def program(self, action):
        self.program_stop_called = action
        return dict(ok=True)


class ReferenceGripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name)/'profile.json'
        self.profile.write_text(json.dumps(dict(
            live_enabled=True, target_e1_mm=3.8, speed=5,
            phases=[dict(until_e1_mm=5.0,max_step_mm=1.0),
                    dict(until_e1_mm=4.0,max_step_mm=.2),
                    dict(until_e1_mm=3.8,max_step_mm=.1)])))
        for name in ('reference_grip', 'fast_position_plan'):
            active = patch('pick_and_hold.Grip.'+name+'.PROFILE', self.profile)
            active.start()
            self.addCleanup(active.stop)
        self.s = FakeService()
        self.s.pose = dict(configuration()[0]['closure']['pose_mm_degrees'])
        self.r = Runner()
        self.g = ReferenceGrip(self.tmp.name, lambda:self.s, lambda:self.r)
        self.g.SETTLE_INTERVAL = .001
        self.g.completed_descent(dict(ok=True,executor='lua_descent'), self.s.pose)

    def start(self):
        self.g.start(dict(ready=True,descent_id=self.g.receipt['id']))
        self.r._thread.join(5)
        self.assertFalse(self.r.active)
        return self.r.result

    def test_two_speed_closure_without_grasp_claim(self):
        result=self.start()
        self.assertTrue(result['ok'],result)
        self.assertEqual(len(self.s.calls),2)
        self.assertEqual(self.s.calls,[(4.8,10),(3.8,5)])
        self.assertFalse(result['grasp_verified'])
        self.assertTrue(result['awaiting_inspection'])
        self.assertEqual(len(json.loads(Path(result['record']).read_text())['steps']),2)
        with self.assertRaises(TeachingError):
            self.g.start(dict(ready=True,descent_id=self.g.receipt['id']))

    def test_poll_no_motion_and_wrong_endpoint_refused(self):
        self.assertTrue(self.g.public(self.s.status())['can_start'])
        self.assertEqual(self.s.calls,[])
        with self.assertRaises(TeachingError):
            self.g.completed_descent(dict(ok=True,executor='lua_descent'),dict(self.s.pose,Z=70.461))

    def test_accepted_48well_executor_never_commands_below_3p9(self):
        reference,digest=configuration()
        reference.update(plate_profile_id='48_well_projected_20261026',
            accepted_plate_grip=True,physical_grip_validated_for_plate=True)
        reference['settings'].update(target_e1_mm=3.9,closing_speed=5)
        with patch.object(self.g,'_configuration',return_value=(reference,digest)):
            self.g.completed_descent(dict(ok=True,executor='lua_descent'),self.s.pose)
            self.assertEqual(self.g.public(self.s.status())['target_e1_mm'],3.9)
            result=self.start()
        self.assertTrue(result['ok'],result)
        self.assertEqual(len(self.s.calls),2)
        self.assertEqual(self.s.calls,[(4.9,10),(3.9,5)])
        self.assertEqual(self.s.calls[-1],(3.9,5))
        self.assertTrue(all(target>=3.9 for target,speed in self.s.calls))
        self.assertFalse(result['grasp_verified'])

    def test_changed_reference_refused_before_dispatch(self):
        reference,digest=configuration()
        with patch('pick_and_hold.Grip.reference_grip.configuration',return_value=(reference,'different')):
            with self.assertRaises(TeachingError):self.start()
        self.assertEqual(self.s.calls,[])

    def test_stop_blocks_completion_and_lift(self):
        original=self.s.torque_report
        def stop():
            self.r.request_stop()
            return original()
        self.s.torque_report=stop
        result=self.start()
        self.assertFalse(result['ok'])
        self.assertEqual(self.s.calls,[(4.8,10)])

    def test_uncertain_command_no_retry(self):
        self.s.result=dict(ok=True,recovered='uncertain')
        result=self.start()
        self.assertFalse(result['ok'])
        self.assertEqual(self.s.calls,[(4.8,10)])

    def test_pose_change_stops(self):
        original=self.s.torque_report
        def moved():
            self.s.pose['X']+=.1
            return original()
        self.s.torque_report=moved
        self.assertFalse(self.start()['ok'])
        self.assertEqual(len(self.s.calls),1)

    def test_missing_feedback_stops(self):
        self.s.torque_report=lambda:dict(ok=False)
        self.assertFalse(self.start()['ok'])
        self.assertEqual(len(self.s.calls),1)

    def test_inspected_offset_passes_position_checks_without_grasp_claim(self):
        original = self.s.move_gripper
        def offset(target, speed):
            result = original(target, speed)
            self.s.e1 = target + .059372
            return result
        self.s.move_gripper = offset
        result = self.start()
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['grasp_verified'])
        self.assertTrue(result['awaiting_inspection'])
        record = json.loads(Path(result['record']).read_text())
        self.assertEqual(record['settle_tolerance_mm'], .07)
        self.assertEqual(record['position_tolerance_mm'], .07)
        self.assertIn('settled_e1_mm', record['steps'][0])

    def test_fresh_report_outside_position_band_stops_without_retry(self):
        original = self.s.torque_report
        def outside_band():
            report=original()
            report['e1_position']+=.071
            return report
        self.s.torque_report=outside_band
        result=self.start()
        self.assertFalse(result['ok'])
        self.assertIn('Fresh grip feedback',result['error'])
        self.assertEqual(len(self.s.calls),1)

    def test_offset_outside_new_settle_tolerance_stops(self):
        original = self.s.move_gripper
        def offset(target, speed):
            result = original(target, speed)
            self.s.e1 = target + .071
            return result
        self.s.move_gripper = offset
        self.g.SETTLE_TIMEOUT = .03
        result = self.start()
        self.assertFalse(result['ok'])
        self.assertIn('did not settle', result['error'])
        self.assertEqual(len(self.s.calls), 1)

    def prepare_3p7(self):
        profile = json.loads(self.profile.read_text())
        profile.update(target_e1_mm=3.7, supervised_trial='e1_3p7_20261020',
            trial_authorization='operator_ui/demonstrations/reference_grip/e1_3p7_20261020.json')
        profile['phases'][-1]['until_e1_mm'] = 3.7
        self.profile.write_text(json.dumps(profile))
        self.g.completed_descent(dict(ok=True,executor='lua_descent'), self.s.pose)

    def test_3p7_single_closure_and_one_attempt_only(self):
        self.prepare_3p7()
        self.assertEqual(self.g.public(self.s.status())['target_e1_mm'],3.7)
        result = self.start()
        self.assertTrue(result['ok'],result)
        self.assertEqual(len(self.s.calls),2)
        self.assertEqual(self.s.calls,[(4.7,10),(3.7,5)])
        self.assertEqual(result['target_e1_mm'],3.7)
        self.assertFalse(result['grasp_verified'])
        self.assertFalse(json.loads(self.profile.read_text())['live_enabled'])
        with self.assertRaises(TeachingError):
            configuration()

    def test_3p7_uncertain_final_command_stops_without_retry(self):
        self.prepare_3p7()
        original = self.s.move_gripper
        def fail_final(target, speed):
            result = original(target, speed)
            return dict(ok=False) if target == 3.7 else result
        self.s.move_gripper = fail_final
        result = self.start()
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.s.calls),2)
        self.assertEqual(self.s.program_stop_called,'stop')
        self.assertFalse(json.loads(self.profile.read_text())['live_enabled'])

    def test_accepted_3p7_remains_enabled_but_descent_receipt_stays_single_use(self):
        self.prepare_3p7()
        profile=json.loads(self.profile.read_text())
        profile['accepted_sequence']='operator_ui/demonstrations/reference_grip/full_calibration_to_home_3p7_20261020_accepted.json'
        self.profile.write_text(json.dumps(profile))
        self.g.completed_descent(dict(ok=True,executor='lua_descent'),self.s.pose)
        self.assertTrue(self.start()['ok'])
        self.assertTrue(json.loads(self.profile.read_text())['live_enabled'])
        with self.assertRaises(TeachingError):self.start()
        self.s.e1=28
        self.g.completed_descent(dict(ok=True,executor='lua_descent'),self.s.pose)
        self.assertTrue(self.start()['ok'])


if __name__ == '__main__':
    unittest.main()
