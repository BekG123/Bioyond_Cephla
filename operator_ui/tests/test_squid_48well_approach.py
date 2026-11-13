"""Real Lua executor with simulated controller; no hardware connection."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from test_squid_48well_endpoint_trial import EndpointTests
import squid_48well_approach as approach


class ApproachTests(unittest.TestCase):
    stop = EndpointTests.stop

    def setUp(self):
        EndpointTests.setUp(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        p = patch.object(approach, 'FOLDER', Path(folder.name))
        p.start(); self.addCleanup(p.stop)

    def test_three_transit_points_no_lowering_or_gripper_commands(self):
        result = approach.execute(self.run, self.s, self.cfg, approach.review(self.s,self.cfg))
        self.assertTrue(result['ok'])
        self.assertEqual([c[1] for c in self.s.robot.calls], [137,137,137])
        self.assertAlmostEqual(self.s.pose['Z'],291.24,places=3)
        self.assertEqual(self.s.grips,[])
        self.assertFalse(result['lowering_executed'])
        self.assertFalse(result['release_executed'])

    def test_changed_grip_stops(self):
        approved=approach.review(self.s,self.cfg)
        original=self.s.robot.finish
        def finish():
            original();self.e1+=.2
        self.s.robot.finish=finish;self.s.robot.lua.globals().MOVFINISH=finish
        with self.assertRaisesRegex(Exception,'Gripper'):
            approach.execute(self.run,self.s,self.cfg,approved)
        self.assertIn('stop',self.stops)

    def test_stop_before_dispatch(self):
        approved=approach.review(self.s,self.cfg);self.run.cancelled=True
        with self.assertRaisesRegex(Exception,'Stopped'):
            approach.execute(self.run,self.s,self.cfg,approved)
        self.assertEqual(self.s.robot.calls,[])

    def test_changed_plan_rejected(self):
        approved=approach.review(self.s,self.cfg);approved['points'][-1]['Z']=270
        with self.assertRaisesRegex(Exception,'changed'):
            approach.execute(self.run,self.s,self.cfg,approved)
        self.assertEqual(self.s.robot.calls,[])

    def test_wrong_grip_and_changed_limits_rejected(self):
        self.e1=3.7
        with self.assertRaisesRegex(Exception,'3.9'):approach.review(self.s,self.cfg)
        self.e1=3.9;cfg=dict(self.cfg,j2_margin_deg=1)
        with self.assertRaisesRegex(Exception,'limits'):approach.review(self.s,cfg)


if __name__=='__main__':unittest.main()
