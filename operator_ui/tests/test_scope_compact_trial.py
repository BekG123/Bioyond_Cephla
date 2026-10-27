"""Four individual reverse moves against fake hardware only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scope_compact_trial as trial
from test_transfer import FakeService
from test_researcher_workflow import FakeRunner
from sequences import get_robot_params


class CompactScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(trial,'OUTPUT',Path(self.temp.name)/'trial.json');p.start();self.addCleanup(p.stop)
        self.plan=json.loads(trial.PLAN.read_text());baseline=json.loads(Path(self.plan['source_trial']).read_text())
        self.cfg=get_robot_params();self.service=FakeService()
        self.service.pose=dict(baseline['final_robot']['pose_mm']);self.service.q=dict(baseline['final_robot']['joints'])
        self.service.envelope=self.plan['envelope'];self.e1=3.70;self.stops=[]
        self.service.external_axes=lambda:dict(E1=self.e1)
        self.service.status=lambda:dict(ok=True,connected=True,errors=[],enabled=True,control_mode={'mode':'auto'},program_state={'state':'running'},pose_mm=self.service.pose_mm(),joints=self.service.joints())
        self.service.program=lambda action:self.stops.append(action) or dict(ok=True)
        self.service.move_cartesian=Mock(wraps=self.service.move_cartesian)
        self.run=FakeRunner();self.run.cancelled=False

    def test_four_exact_moves_speed40_finish_at_saved_home(self):
        approved=trial.review(self.service,self.cfg)
        expected=list(reversed([self.plan['start']]+self.plan['points']))[1:]
        self.assertEqual(approved['points'],expected)
        result=trial.execute(self.run,self.service,self.cfg,approved)
        self.assertTrue(result['ok']);self.assertEqual(result['moves'],4)
        self.assertEqual(self.service.pose,self.plan['start'])
        self.assertTrue(all(c.kwargs==dict(speed=40,interpolation='linear') for c in self.service.move_cartesian.call_args_list))
        self.assertEqual(self.service.grips,[]);self.assertEqual(self.stops,[])
        with self.assertRaisesRegex(Exception,'already attempted'):trial.review(self.service,self.cfg)

    def test_wrong_winding_refuses_before_motion(self):
        self.service.q['J4']+=360
        with self.assertRaisesRegex(Exception,'winding'):trial.review(self.service,self.cfg)
        self.assertEqual(self.service.moves,[])

    def set_home(self):
        baseline=json.loads(Path(self.plan['source_trial']).read_text())
        self.service.pose=dict(self.plan['start'])
        self.service.q=dict(baseline['steps'][0]['joints_before'])

    def test_forward_four_moves_preserves_ending_and_reverse_record(self):
        self.set_home()
        trial.OUTPUT.write_text('preserve reverse record')
        approved=trial.review_forward(self.service,self.cfg)
        self.assertEqual(approved['points'],self.plan['points'])
        result=trial.execute_forward(self.run,self.service,self.cfg,approved)
        self.assertTrue(result['ok']);self.assertEqual(result['moves'],4)
        self.assertEqual(self.service.pose,self.plan['points'][-1])
        self.assertEqual(trial.OUTPUT.read_text(),'preserve reverse record')
        self.assertTrue(all(c.kwargs==dict(speed=40,interpolation='linear') for c in self.service.move_cartesian.call_args_list))
        self.assertEqual(self.service.grips,[]);self.assertEqual(self.stops,[])
        with self.assertRaisesRegex(Exception,'already attempted'):trial.review_forward(self.service,self.cfg)

    def test_forward_wrong_start_and_winding_refused(self):
        with self.assertRaisesRegex(Exception,'Pose mismatch'):trial.review_forward(self.service,self.cfg)
        self.set_home();self.service.q['J4']+=360
        with self.assertRaisesRegex(Exception,'winding'):trial.review_forward(self.service,self.cfg)
        self.assertEqual(self.service.moves,[])

    def test_stopped_does_not_dispatch(self):
        approved=trial.review(self.service,self.cfg);self.run.cancelled=True
        with self.assertRaisesRegex(Exception,'Stopped'):trial.execute(self.run,self.service,self.cfg,approved)
        self.assertEqual(self.service.moves,[]);self.assertEqual(self.stops,['stop'])

    def test_first_move_failure_stops_without_retry(self):
        approved=trial.review(self.service,self.cfg);self.service.motion_failure='stale'
        with self.assertRaises(Exception):trial.execute(self.run,self.service,self.cfg,approved)
        self.assertEqual(len(self.service.moves),1);self.assertEqual(self.stops,['stop'])


if __name__=='__main__':unittest.main()
