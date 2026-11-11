"""One native E1 move, accepted caller endpoint and speed 5; no hardware."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gripper_closure import POLICY, closure_plan, closing_targets
from robot_service import RobotService, MOVETYPE_GRIPPER, PF_SPEED, PF_E1


class ContinuousClosureTests(unittest.TestCase):
    def test_exact_one_mm_finish_at5_after_approach10(self):
        for start,target in ((28,25),(28,3.9),(7,3.9),(5,3.7),(28,3.8)):
            with self.subTest(start=start,target=target):
                plan=closure_plan(start,target);commands=plan['commands']
                self.assertEqual(plan['closure_policy'],POLICY)
                self.assertEqual(plan['command_count'],2)
                self.assertEqual([c['speed'] for c in commands],[10,5])
                self.assertEqual(closing_targets(start,target),[round(target+1,10),target])
                self.assertAlmostEqual(commands[-1]['delta_mm'],1)
                self.assertEqual(commands[-1]['phase'],'finish')
                self.assertFalse(plan['dispatch'])

    def test_already_in_final_millimeter_never_uses_fast_speed(self):
        for start in (3.9,4.2,4.9):
            commands=closure_plan(start,3.9)['commands']
            self.assertEqual(len(commands),1)
            self.assertEqual(commands[0]['speed'],5)
            self.assertEqual(commands[0]['target_e1_mm'],3.9)

    def test_invalid_or_outward_targets_refused(self):
        for start, target in ((28, float('nan')), (float('inf'), 25),
                              (28, -1), (29, 25), (3.9, 28), (True, 0)):
            with self.subTest(start=start, target=target):
                with self.assertRaises(ValueError):
                    closure_plan(start, target)

    def test_service_dispatches_one_native_external_axis_command(self):
        service = RobotService.__new__(RobotService)
        service._locked = lambda fn: fn()
        service._hostpoint = Mock(return_value={'ok': True})
        service._read_gripper_report = Mock(return_value={
            'e1_position': 3.9, 'e1_torque': 0, 'ok': True})
        service._is_unknown_state = Mock(return_value=False)
        result = service.move_gripper(3.9, speed=5)
        self.assertTrue(result['ok'])
        service._hostpoint.assert_called_once()
        params, kind, timeout = service._hostpoint.call_args.args
        self.assertEqual(kind, MOVETYPE_GRIPPER)
        self.assertEqual(params[PF_SPEED], 5)
        self.assertEqual(params[PF_E1], 3.9)
        self.assertGreater(timeout, 0)


if __name__ == '__main__':
    unittest.main()
