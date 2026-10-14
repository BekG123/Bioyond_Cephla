"""No hardware: shared disk/ArUco planner regressions from live pose logs."""
import unittest
from test_transfer import FakeService, PARAMS
from autonomy import AlignmentGuard, alignment_plan, TransferError
from sequences import Runner, seq_align, seq_descend, _ik_j2j3

START = dict(X=293.115, Y=56.588, Z=270.453, Rz=-6.443)
JOINTS = dict(J1=231.854, J2=82.53354, J3=52.34679, J4=-141.3234)
ENV = dict(X=(0, 550), Y=(-350, 350), Z=(0, 420))
NEAR = dict(x=119.78, y=136.86, rz=-6.49, z_calibrated=35.04, span_mm=85)

class WristService(FakeService):
    def __init__(self):
        super().__init__()
        self.rotations = []
        self.rotation_failure = None

    def move_cartesian(self, x, y, z, rz, speed=10, interpolation='linear'):
        if abs(rz - self.pose['Rz']) > 0.05:
            raise AssertionError('wrist rotation dispatched as MoveL')
        return super().move_cartesian(x, y, z, rz, speed, interpolation)

    def rotate_to_rz(self, rz_target, speed, force_delta=None):
        self.rotations.append((self.pose.copy(), rz_target, speed, force_delta))
        self.motion_failure = self.rotation_failure
        p = self.pose
        result = super().move_cartesian(p['X'], p['Y'], p['Z'], rz_target, speed, 'joint')
        if self.rotation_failure == 'joint':
            self.q['J2'] += 1
        if self.rotation_failure == 'xyz':
            self.pose['X'] += 2
        return result


class AlignmentTests(unittest.TestCase):
    def test_live_yaw_uses_small_movej_segments_then_linear_translation(self):
        svc = WristService()
        svc.pose = dict(X=304.203, Y=21.388, Z=285.175, Rz=10.253)
        svc.q = dict(J1=246.576, J2=70.183253, J3=53.321055, J4=-113.251308)
        result = seq_align(Runner(), svc,
                           dict(x=317.643, y=-69.599, rz=92.0687, z_calibrated=100), 300)
        self.assertTrue(result['ok'], result)
        self.assertEqual(len(svc.rotations), 3)
        for before, rz, speed, delta in svc.rotations:
            self.assertEqual(before['Z'], 300)
            self.assertAlmostEqual(before['X'], 304.203)
            self.assertAlmostEqual(before['Y'], 21.388)
            self.assertLessEqual(abs(delta), 30)
            self.assertEqual(speed, 30)
        self.assertAlmostEqual(svc.pose['X'], 317.643)
        self.assertAlmostEqual(svc.pose['Rz'], 92.0687)
        self.assertEqual(svc.pose['Z'], 300)
        self.assertEqual(svc.grips, [])

    def test_bad_rotation_feedback_stops_before_next_segment(self):
        for failure in ('recovered', 'stale', 'joint', 'xyz'):
            with self.subTest(failure=failure):
                svc = WristService()
                svc.rotation_failure = failure
                result = seq_align(Runner(), svc,
                                   dict(x=340, y=0, rz=65, z_calibrated=100), 300)
                self.assertFalse(result['ok'], result)
                self.assertEqual(len(svc.rotations), 1)
                self.assertEqual(len(svc.moves), 1)
                self.assertEqual(svc.grips, [])

    def test_rotation_height_size_and_stop_guards(self):
        for height, angle, stopped in ((299, 5, False), (300, 31, False), (300, 5, True)):
            with self.subTest(height=height, angle=angle, stopped=stopped):
                svc, run = WristService(), Runner()
                svc.pose['Z'] = height
                if stopped:
                    run.request_stop()
                with self.assertRaises(TransferError):
                    AlignmentGuard(svc, run, PARAMS).rotate_to_rz(angle)
                self.assertEqual(svc.rotations + svc.moves, [])

    def test_descent_envelope_check_still_precedes_all_motion(self):
        svc = WristService()
        svc.envelope['Z'] = (100, 400)
        result = seq_align(Runner(), svc,
                           dict(x=340, y=0, rz=25, z_calibrated=71), 300)
        self.assertFalse(result['ok'])
        self.assertIn('Z envelope', result['error'])
        self.assertEqual(svc.moves + svc.rotations, [])

    def test_endpoint_branch_switch_is_not_a_path(self):
        self.assertLess(abs(_ik_j2j3(NEAR['x'], NEAR['y'], JOINTS['J2'])[0]), 93)
        with self.assertRaisesRegex(TransferError, 'J2'):
            alignment_plan(START, NEAR, JOINTS, PARAMS, ENV)

    def test_rejected_alignment_does_not_even_lift(self):
        svc = FakeService()
        svc.pose, svc.q, svc.envelope = START.copy(), JOINTS.copy(), ENV.copy()
        result = seq_align(Runner(), svc, NEAR, 300)
        self.assertFalse(result['ok'])
        self.assertEqual(svc.moves + svc.grips, [])

    def test_missing_joints_fail_closed(self):
        with self.assertRaises(TransferError):
            alignment_plan(START, NEAR, {}, PARAMS, ENV)

    def test_valid_alignment_no_grip(self):
        svc = FakeService()
        result = seq_align(Runner(), svc, dict(x=340, y=0, rz=0, z_calibrated=100), 300)
        self.assertTrue(result['ok'], result)
        self.assertEqual(svc.grips, [])
        self.assertEqual(svc.pose['Z'], 300)

    def test_closed_jaws_prevent_descent(self):
        svc = FakeService()
        result = seq_descend(Runner(), svc, dict(x=326,y=0,rz=0,z_calibrated=100,span_mm=85))
        self.assertFalse(result['ok'])
        self.assertIn('open jaws', result['error'])
        self.assertEqual(svc.moves + svc.grips, [])

    def test_recovered_move_stops(self):
        svc = FakeService()
        svc.motion_failure = 'recovered'
        result = seq_align(Runner(), svc, dict(x=340,y=0,rz=0,z_calibrated=100),300)
        self.assertFalse(result['ok'])
        self.assertEqual(len(svc.moves), 1)

    def test_rotation_lift_precedes_rotation(self):
        svc = FakeService()
        svc.pose['Z'] = 270
        plan = alignment_plan(svc.pose, dict(x=340,y=0,rz=10,z_calibrated=100), svc.q, PARAMS, ENV)
        for point in plan:
            if point['Rz'] != 0:
                self.assertGreaterEqual(point['Z'], 300)

if __name__ == '__main__':
    unittest.main()
