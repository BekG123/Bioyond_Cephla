from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_squid_handling as fixture
import hamilton_reteach_trial as trial
from trajectory_queue import LuaTrajectory,prepare_points


class ReteachTests(unittest.TestCase):
    setUp=fixture.SquidHandlingTests.setUp
    stop=fixture.SquidHandlingTests.stop
    jaw=fixture.SquidHandlingTests.jaw

    def test_actual_lua_exact_candidate_at_137_without_claw_commands(self):
        output=Path(self.temp.name)/'trial.json'
        self.s.external_axes=lambda:{'E1':self.e1}
        with patch.object(trial,'OUTPUT',output):
            approved=trial.review(self.s,self.cfg)
            self.run.start('trial',trial.execute,self.s,self.cfg,approved)
            result=self.run.finish()
            self.assertTrue(result['ok'],result)
            self.assertEqual([call[1] for call in self.s.robot.calls],[137]*3)
            self.assertEqual(self.s.grips,[])
            self.assertEqual(json.loads(output.read_text())['status'],'completed')
            with self.assertRaisesRegex(Exception,'already attempted'):trial.review(self.s,self.cfg)
            for k,v in trial.reference()['endpoint'].items():self.assertAlmostEqual(self.s.pose[k],v,places=4)
            approved=trial.review(self.s,self.cfg,reverse=True)
            self.run.start('reverse_trial',trial.execute,self.s,self.cfg,approved)
            result=self.run.finish()
            self.assertTrue(result['ok'],result)
            self.assertEqual([call[1] for call in self.s.robot.calls],[137]*6)
            self.assertEqual(self.s.grips,[])
            saved=json.loads(trial.output_path(True).read_text())
            self.assertEqual(saved['status'],'completed')
            self.assertTrue(saved['plan']['forward_trial_sha256'])
            with self.assertRaisesRegex(Exception,'already attempted'):trial.review(self.s,self.cfg,reverse=True)
        for k,v in trial.reference()['routes']['forward'][0].items():self.assertAlmostEqual(self.s.pose[k],v,places=4)

    def test_reverse_requires_verified_forward_completion(self):
        output=Path(self.temp.name)/'trial.json'
        output.write_text(json.dumps({'status':'failed_or_uncertain'}))
        with patch.object(trial,'OUTPUT',output):
            with self.assertRaisesRegex(Exception,'Successful matching forward'):
                trial.review(self.s,self.cfg,reverse=True)
        self.assertFalse(self.s.robot.calls)

    def test_rejects_changed_points_settings_or_unreviewed_flag(self):
        path=trial.reference()['routes']['forward'];points=deepcopy(path[1:])
        points[-1]['X']+=.01
        with self.assertRaisesRegex(Exception,'exact approved'):
            prepare_points(path[0],self.s.q,points,self.cfg,reviewed=True,hamilton_trial=True)
        with self.assertRaisesRegex(Exception,'explicit review'):
            prepare_points(path[0],self.s.q,path[1:],self.cfg,hamilton_trial=True)
        with self.assertRaisesRegex(Exception,'settings changed'):
            trial.check_route(path[0],path[1:],self.s.q,{**self.cfg,'j4_hard_abs_deg':280},self.s.envelope)
        self.assertFalse(self.s.robot.calls)

    def test_stop_or_fault_does_not_dispatch(self):
        path=trial.reference()['routes']['forward']
        self.run.stopped=lambda:True
        with self.assertRaisesRegex(Exception,'stopped'):
            LuaTrajectory(self.s).execute(self.run,path[0],self.s.q,path[1:],self.cfg,137,
                lambda *args:None,reviewed=True,home_speed137=True,hamilton_trial=True)
        self.assertFalse(self.s.robot.calls)


if __name__=='__main__':unittest.main()
