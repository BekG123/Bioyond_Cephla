"""Exact latest route via explicit repeat buttons, using real Lua and fake hardware."""
import json
import shutil
import unittest
from unittest.mock import Mock

from test_pruned_replay import PrunedReplayTests, HERE
from latest_hamilton import LatestHamilton, PATH_ID
from researcher_teaching import TeachingError


class LatestTests(unittest.TestCase):
    def test_startup_refusal_does_not_mask_an_older_uncertain_route(self):
        from home_attempts import HomeTravelNotStarted
        self.latest.attempts.mkdir(parents=True, exist_ok=True)
        first = self.latest.attempts/'0001.json'
        latest = self.latest.attempts/'0002.json'
        first.write_text(json.dumps(dict(status='stopped_or_failed')))
        latest.write_text(json.dumps(dict(status='stopped_or_failed',
            home_startup_refusal=HomeTravelNotStarted('test').evidence)))
        with self.assertRaisesRegex(TeachingError, 'previous route'):
            self.latest.check_previous_attempt()
        first.write_text(json.dumps(dict(status='completed')))
        self.latest.check_previous_attempt()
        latest.write_text('{')
        with self.assertRaises(TeachingError):
            self.latest.check_previous_attempt()

    def setUp(self):
        PrunedReplayTests.setUp(self)
        source=HERE/'reports/trajectory_smoothing/entry_forward_3mm'
        shutil.copytree(source,self.root/'reports/trajectory_smoothing/entry_forward_3mm')
        self.latest=LatestHamilton(self.folder,lambda:self.s,lambda:self.run,lambda:self.s.cfg,self.prepare,Mock())
        self.s.status=lambda:dict(ok=True,connected=True,errors=[],pose_mm=self.s.pose,joints=self.s.q)

    def start(self):
        status=self.latest.public(self.s.status())
        return self.latest.start(dict(ready=True,path_id=PATH_ID,direction=status['direction']))

    def test_both_directions_use_three_commands_at137_with_fresh_attempt_records(self):
        original=(self.folder/'replay_permission.json').read_bytes()
        self.start();result=self.run.finish()
        self.assertEqual(result['speed'],137);self.assertEqual(result['direction'],'toward_home')
        self.assertEqual(len(self.s.robot.calls),3)
        self.assertTrue(all(c[1]==137 for c in self.s.robot.calls))
        # New start requires another explicit press; completed run alone does not schedule one.
        self.assertFalse(self.run.active)
        self.assertEqual(len(list(self.latest.attempts.glob('*.json'))),1)
        # Fake Lua tracks an append-only call history; use a fresh fake controller for this traversal.
        from test_trajectory_queue import Controller
        # Fake check_path only models planar joints; supply the measured linear-axis endpoint.
        self.s.q['J1']=self.data['trajectory'][-1]['joints']['J1']
        self.s.robot=Controller(self.s)
        self.start();result=self.run.finish()
        self.assertEqual(result['direction'],'to_hamilton')
        self.assertEqual(len(list(self.latest.attempts.glob('*.json'))),2)
        self.assertEqual((self.folder/'replay_permission.json').read_bytes(),original)

    def test_missing_confirmation_displaced_start_and_stale_direction_refused(self):
        with self.assertRaises(TeachingError):self.latest.start(dict(path_id=PATH_ID,direction='toward_home'))
        with self.assertRaises(TeachingError):self.latest.start(dict(ready=True,path_id=PATH_ID,direction='to_hamilton'))
        self.s.pose['X']+=3
        self.assertFalse(self.latest.public(self.s.status())['can_start'])
        self.assertEqual(self.s.robot.jobs,[])

    def test_failure_survives_restart_and_blocks_button_retry(self):
        self.start();self.latest.stop()
        with self.assertRaises(Exception):self.run.finish()
        reloaded=LatestHamilton(self.folder,lambda:self.s,lambda:self.run,lambda:self.s.cfg,self.prepare,Mock())
        self.assertFalse(reloaded.public(self.s.status())['can_start'])
        with self.assertRaises(TeachingError):self.start()
        self.assertEqual(self.s.robot.calls,[])

    def test_older_queue_and_tampered_candidate_do_not_move(self):
        from test_trajectory_queue import Controller
        self.s.robot=Controller(self.s,legacy=130)
        with self.assertRaises(TeachingError):self.start()
        self.assertEqual(self.s.robot.jobs,[])
        path=self.root/'reports/trajectory_smoothing/entry_forward_3mm/candidate.json'
        path.write_text(path.read_text()+' ')
        with self.assertRaises(TeachingError):self.latest.reviewed()


if __name__=='__main__':unittest.main()
