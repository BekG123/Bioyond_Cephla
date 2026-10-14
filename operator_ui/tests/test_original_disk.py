"""Original routine wiring and retained guards; fake hardware only."""
import unittest
from unittest.mock import patch

from test_fast_disk import DiskService, Vision
from test_transfer import PARAMS, CAM
from sequences import Runner
from original_disk import OriginalDiskGuard, run_original_disk
from autonomy import TransferError


class OriginalVision(Vision):
    def evaluate_ways(self, *args):
        result = super().evaluate_ways(*args)
        for way in result.get('ways', []):
            way.update(conv_radius=326, grasp_radius=340, ang_diff=0)
            way['solve'].update(detected=True, mark=[0, 0, 0])
        return result

    def solve(self, *args, **kwargs):
        return self.evaluate_ways(*args)['ways'][0]['solve']


class OriginalDiskTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.run = DiskService(), Runner()
        self.run.state = 'running'
        self.vision = OriginalVision(self.svc, dict(self.svc.pose))
        self.guard = OriginalDiskGuard(self.svc, self.run, PARAMS)

    def test_real_original_loop_and_z_refine(self):
        result = run_original_disk(self.run, self.svc, CAM, self.vision, PARAMS)
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.run.target['source'], 'original_two_circle')
        self.assertEqual(self.run.target['z_detail']['samples'], [300, 300, 300])
        self.assertEqual([p[2] for p in self.svc.moves], [310, 300])
        self.assertEqual(self.svc.grips, [])

    def test_routes_select_original_not_fast(self):
        import app as console
        from sequences_original import seq_find_disk as saved_original
        client = console.app.test_client()
        with patch.object(console.runner, 'start', return_value={'ok': True}) as start:
            for route in ('/seq/find_disk', '/seq/find_disk_original'):
                for bad in ({}, dict(confirm=True, cell_clear=True, empty_gripper='true')):
                    self.assertEqual(client.post(route, json=bad).status_code, 400)
                start.assert_not_called()
                self.assertEqual(client.post(route, json=dict(confirm=True, cell_clear=True, empty_gripper=True)).status_code, 200)
                self.assertIs(start.call_args.args[1], saved_original)
                self.assertIs(start.call_args.args[2], console.svc)
                self.assertEqual(len(start.call_args.args), 5)
                start.reset_mock()

    def test_saved_original_matches_git(self):
        import subprocess
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        expected = subprocess.check_output(['git', 'show', '99ebe5d:operator_ui/sequences.py'], cwd=root).decode('utf-8')
        actual = (root / 'operator_ui/sequences_original.py').read_text(encoding='utf-8')
        self.assertEqual(actual.replace('\r\n', '\n'), expected.replace('\r\n', '\n'))

    def test_exact_original_runs_z_refine_without_new_wrapper(self):
        import sequences_original as saved
        result = saved.seq_find_disk(self.run, self.svc, CAM, self.vision)
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.run.target['z_detail']['samples'], [300, 300, 300])
        self.assertEqual([p[2] for p in self.svc.moves], [310, 300])
        self.assertNotIn('source', self.run.target)

    def test_missing_or_holding_telemetry_stops_before_original_loop(self):
        with patch('sequences.seq_find_disk_legacy') as original:
            self.svc.torque = -187
            self.assertFalse(run_original_disk(self.run, self.svc, CAM, self.vision, PARAMS)['ok'])
            self.svc.torque_report = lambda: dict(ok=True, telemetry_live=False)
            self.assertFalse(run_original_disk(self.run, self.svc, CAM, self.vision, PARAMS)['ok'])
            original.assert_not_called()

    def test_low_wrist_motion_is_rejected(self):
        self.svc.pose['Z'] = 290
        with self.assertRaises(TransferError):
            self.guard.rotate_to_rz(5)
        with self.assertRaises(TransferError):
            self.guard.move_cartesian(327, 0, 290, 1)
        self.assertEqual(self.svc.moves, [])

    def test_wrist_chunks_and_full_path_limit_check(self):
        self.guard.rotate_to_rz(25, force_delta=25)
        self.assertEqual(len(self.svc.rotations), 3)
        self.assertTrue(all(r[1] == 5 for r in self.svc.rotations))
        self.svc.rotations.clear()
        with self.assertRaises(TransferError):
            self.guard.rotate_to_rz(-175, force_delta=-200)
        self.assertEqual(self.svc.rotations, [])

    def test_uncertain_arrival_is_not_retried(self):
        for failure in ('stale', 'recovered'):
            self.svc.motion_failure = failure
            self.run.target = {'stale': True}
            before = len(self.svc.moves)
            result = run_original_disk(self.run, self.svc, CAM, self.vision, PARAMS)
            self.assertFalse(result['ok'])
            self.assertEqual(len(self.svc.moves)-before, 1)
            self.assertIsNone(self.run.target)


if __name__ == '__main__':
    unittest.main()
