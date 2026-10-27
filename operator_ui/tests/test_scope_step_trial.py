"""Offline one-shot sequential trial tests; no robot or camera connections."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scope_step_trial as trial
from test_transfer import FakeService
from test_researcher_workflow import FakeRunner
from sequences import get_robot_params


class ScopeStepTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(trial,'OUTPUT',Path(self.temp.name)/'trial.json');p.start();self.addCleanup(p.stop)
        plan=json.loads(trial.PLAN.read_text())
        self.cfg=get_robot_params();self.service=FakeService()
        self.service.pose=dict(plan['start']);self.service.q=dict(plan['live_robot']['joints'])
        self.service.envelope=plan['envelope'];self.e1=3.70;self.stops=[]
        self.service.external_axes=lambda:dict(E1=self.e1)
        self.service.status=lambda:dict(ok=True,connected=True,errors=[],enabled=True,control_mode={'mode':'auto'},program_state={'state':'running'},pose_mm=self.service.pose_mm(),joints=self.service.joints())
        self.service.program=lambda action:self.stops.append(action) or dict(ok=True)
        self.service.move_cartesian=Mock(wraps=self.service.move_cartesian)
        self.run=FakeRunner();self.run.cancelled=False

    def test_full_trial_uses_individual_speed40_and_preserves_gripper(self):
        approved=trial.review(self.service,self.cfg)
        result=trial.execute(self.run,self.service,self.cfg,approved)
        self.assertTrue(result['ok']);self.assertFalse(result['lua_queue_used'])
        self.assertEqual(len(self.service.moves),121)
        self.assertTrue(all(call.kwargs==dict(speed=40,interpolation='linear') for call in self.service.move_cartesian.call_args_list))
        self.assertEqual(self.service.grips,[]);self.assertEqual(self.stops,[])
        with self.assertRaisesRegex(Exception,'already attempted'):trial.review(self.service,self.cfg)

    def test_stop_before_dispatch_sends_no_move(self):
        approved=trial.review(self.service,self.cfg);self.run.cancelled=True
        with self.assertRaisesRegex(Exception,'Stopped'):trial.execute(self.run,self.service,self.cfg,approved)
        self.assertEqual(self.service.moves,[]);self.assertEqual(self.stops,['stop'])

    def test_failed_first_move_has_no_retry(self):
        approved=trial.review(self.service,self.cfg);self.service.motion_failure='stale'
        with self.assertRaises(Exception):trial.execute(self.run,self.service,self.cfg,approved)
        self.assertEqual(len(self.service.moves),1);self.assertEqual(self.stops,['stop'])

    def test_joint_winding_change_stops_after_first_move(self):
        approved=trial.review(self.service,self.cfg);original=self.service.move_cartesian
        def changed(*args,**kwargs):
            result=original(*args,**kwargs);self.service.q['J4']+=360;return result
        self.service.move_cartesian=changed
        with self.assertRaisesRegex(Exception,'winding'):trial.execute(self.run,self.service,self.cfg,approved)
        self.assertEqual(len(self.service.moves),1)

    def test_gripper_change_stops_after_first_move(self):
        approved=trial.review(self.service,self.cfg);original=self.service.move_cartesian
        def changed(*args,**kwargs):
            result=original(*args,**kwargs);self.e1+=.2;return result
        self.service.move_cartesian=changed
        with self.assertRaisesRegex(Exception,'Gripper'):trial.execute(self.run,self.service,self.cfg,approved)
        self.assertEqual(len(self.service.moves),1)

    def test_changed_workspace_or_policy_refuses_before_motion(self):
        with self.assertRaisesRegex(Exception,'policy'):trial.review(self.service,{**self.cfg,'j4_pref_abs_deg':150.})
        self.service.envelope={**self.service.envelope,'Y':[-250,100]}
        with self.assertRaisesRegex(Exception,'Workspace'):trial.review(self.service,self.cfg)
        self.assertEqual(self.service.moves,[])


if __name__=='__main__':unittest.main()
