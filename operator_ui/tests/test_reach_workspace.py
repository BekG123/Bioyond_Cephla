"""Offline reach boundary regression checks; no controller connection."""
import json
import sys
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI))
from autonomy import ik, check_path, TransferError
from robot_service import _reach_guard
from sequences import get_robot_params, _reach_block


class ReachWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.params = get_robot_params()
        self.envelope = json.loads((UI / 'envelope.json').read_text())

    def test_boundary_agrees_between_planner_sequences_and_host(self):
        p = self.params
        for radius, permitted in [(389.99, True), (390.0, True), (390.01, False)]:
            with self.subTest(radius=radius):
                x, y = p['base_x_mm'] + radius, p['base_y_mm']
                self.assertEqual(_reach_guard(x, y, None) is None, permitted)
                self.assertEqual(_reach_block(x, y, 0) is None, permitted)
                if permitted:
                    ik(x, y, (0, 180), p)
                else:
                    with self.assertRaises(TransferError):
                        ik(x, y, (0, 180), p)

    def test_requested_box_remains_enabled(self):
        self.assertTrue(self.envelope['enabled'])
        self.assertEqual(self.envelope['envelope'],
                         dict(X=[200., 450.], Y=[-250., 380.], Z=[70., 400.]))

    def test_y_boundary_is_checked_independently_of_reach(self):
        p = dict(X=200., Y=380., Z=266., Rz=0.)
        a, b = ik(p['X'], p['Y'], (60, 200), self.params)
        joints = dict(J2=a, J3=b, J4=0.)
        check_path(p, p, joints, self.params, self.envelope['envelope'])
        with self.assertRaisesRegex(TransferError, 'Y envelope'):
            check_path(p, {**p, 'Y':380.01}, joints, self.params,
                       self.envelope['envelope'])

    def test_screenshot_pose_still_requires_wrist_review(self):
        # Historical rejection under the original wrist policy.
        self.params.update(j4_pref_abs_deg=150., j4_hard_abs_deg=205.)
        p = dict(X=226.422, Y=373.524, Z=266.187, Rz=89.097)
        q = dict(J2=89.719, J3=150.46585, J4=208.91191)
        self.assertIsNone(_reach_guard(p['X'], p['Y'], None))
        self.assertIsNone(_reach_block(p['X'], p['Y'], q['J2']))
        with self.assertRaisesRegex(TransferError, 'J4'):
            check_path(p, p, q, self.params, self.envelope['envelope'])

    def test_buffered_wrist_envelope_is_symmetric_and_retains_winding(self):
        from sequences import J4_HARD_ABS, J4_PREF_ABS
        self.assertEqual(self.params['j4_pref_abs_deg'],220.)
        self.assertEqual(self.params['j4_hard_abs_deg'],220.)
        self.assertEqual(J4_HARD_ABS,215.)
        self.assertEqual(J4_PREF_ABS,215.)
        p = dict(X=326., Y=0., Z=300., Rz=0.)
        for angle in (-276., -220., -215.01, -215., 0., 215., 215.01, 220., 276.):
            with self.subTest(angle=angle):
                q = dict(J2=60., J3=60., J4=angle)
                if abs(angle) <= 215:
                    result = check_path(p,p,q,self.params,self.envelope['envelope'])
                    self.assertAlmostEqual(result['J4'],angle)
                else:
                    with self.assertRaisesRegex(TransferError,'J4'):
                        check_path(p,p,q,self.params,self.envelope['envelope'])


if __name__ == '__main__':
    unittest.main()
