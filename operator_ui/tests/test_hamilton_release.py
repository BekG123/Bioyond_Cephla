"""Release and all four legs against the real Lua executor with fake hardware."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_squid_handling as fixture
import hamilton_release_20261108 as release
from trajectory_queue import LuaTrajectory, prepare_points


class ReleaseTests(unittest.TestCase):
    stop = fixture.SquidHandlingTests.stop
    jaw = fixture.SquidHandlingTests.jaw

    def setUp(self):
        fixture.SquidHandlingTests.setUp(self)
        _, receipt, _, _ = release.reference()
        self.s.pose = dict(receipt['final_robot']['pose_mm'])
        self.s.q = dict(receipt['final_robot']['joints'])
        self.e1 = receipt['final_robot']['external_axes']['E1']
        self.output = Path(self.temp.name)/'release.json'
        p = patch.object(release,'OUTPUT',self.output)
        p.start(); self.addCleanup(p.stop)

    def test_release_then_four_legs_and_no_replay(self):
        plan = release.review(self.s,self.cfg)
        self.run.start('release',release.execute,self.s,self.cfg,plan)
        result = self.run.finish()
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.s.grips,[7])
        self.assertEqual([x[1] for x in self.s.robot.calls],[5,5,137,137])
        release.near(self.s.pose,plan['route'][-1],.01)
        self.assertEqual(len(json.loads(self.output.read_text())['steps']),4)
        with self.assertRaisesRegex(Exception,'already attempted'):release.review(self.s,self.cfg)

    def test_failed_release_never_moves_arm(self):
        plan=release.review(self.s,self.cfg)
        self.s.move_gripper=lambda *a,**kw:dict(ok=False,error='fixture jam')
        self.run.start('release',release.execute,self.s,self.cfg,plan)
        with self.assertRaisesRegex(Exception,'Release uncertain'):
            self.run.finish()
        self.assertFalse(self.s.robot.calls)
        self.assertIn('stop',self.stops)

    def test_slow_lift_and_route_pinning(self):
        plan=release.review(self.s,self.cfg);start,target=plan['route'][:2]
        with self.assertRaisesRegex(Exception,'at most 5'):
            LuaTrajectory(self.s).execute(self.run,start,self.s.q,[target],self.cfg,137,
                lambda *a:None,reviewed=True,home_speed137=True,hamilton_release=True)
        with self.assertRaisesRegex(Exception,'exact Hamilton'):
            prepare_points(start,self.s.q,[{**target,'X':target['X']+1}],self.cfg,
                reviewed=True,hamilton_release=True)
        self.assertFalse(self.s.robot.calls)

    def test_unsettled_release_and_stop_never_move_arm(self):
        plan=release.review(self.s,self.cfg)
        self.s.move_gripper=lambda *a,**kw:dict(ok=True)
        self.run.start('release',release.execute,self.s,self.cfg,plan)
        with self.assertRaisesRegex(Exception,'did not settle'):
            self.run.finish()
        self.assertFalse(self.s.robot.calls)


if __name__=='__main__':unittest.main()
