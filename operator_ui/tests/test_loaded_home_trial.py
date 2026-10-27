"""Loaded roundtrip uses real Lua with fake motion and temporary trial storage."""
from pathlib import Path
import sys
import tempfile
import hashlib
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import loaded_home_trial as trial
from autonomy import check_path, TransferError
from test_transfer import FakeService
from sequences import get_robot_params
PARAMS=get_robot_params()
from test_trajectory_queue import Controller
from test_researcher_workflow import FakeRunner

class LoadedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.output=Path(self.tmp.name)/'result.json'
        p=patch.object(trial,'OUTPUT',self.output);p.start();self.addCleanup(p.stop)
        self.s=FakeService();self.s.envelope={'X':(200,450),'Y':(-250,100),'Z':(70,400)}
        home=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
        self.s.q=check_path(self.s.pose,home,self.s.q,PARAMS,self.s.envelope);self.s.pose=home
        self.e1=3.8
        self.s.external_axes=lambda:{'E1':self.e1}
        self.s.robot=Controller(self.s)
        self.s.robot.lua.globals().GetCJoints=lambda:self.s.robot.lua.table_from([self.s.q[k] for k in ('J1','J2','J3','J4')]+[0,0,self.e1,-2,0,0,0,0])
        self.s._locked=lambda fn:fn()
        def stop(action):
            self.assertEqual(action,'stop')
            self.s.robot.program_state='stopped';self.s.robot.released.set()
            return dict(ok=True)
        self.s.program=stop
        self.s.status=lambda:dict(ok=True,connected=True,errors=[],enabled=True,control_mode={'mode':'auto'},program_state={'state':self.s.robot.program_state},pose_mm=self.s.pose_mm(),joints=self.s.joints())
        self.s.rotate_to_rz=lambda rz,speed,force_delta:self.s.move_cartesian(self.s.pose['X'],self.s.pose['Y'],self.s.pose['Z'],rz,speed)
        self.run=FakeRunner();self.run.cancelled=False

    def test_both_directions_and_all_queued_speeds_preserve_claw(self):
        plan=trial.review(self.s,PARAMS)
        self.assertEqual(plan['pickup'],dict(X=298.78,Y=-65.68,Z=70.46,Rz=85.67))
        result=trial.execute(self.run,self.s,PARAMS,plan)
        self.assertTrue(result['ok']);trial.near(self.s.pose,plan['home'])
        self.assertEqual(len(self.s.robot.calls),6)
        self.assertTrue(all(c[1]==137 and c[0][6]==3.8 for c in self.s.robot.calls))
        self.assertEqual(len(self.s.moves),6) # only the six wrist segments
        self.assertEqual(self.s.grips,[])
        with self.assertRaisesRegex(TransferError,'already attempted'):trial.review(self.s,PARAMS)

    def test_changed_claw_refuses_before_motion(self):
        self.e1=3.5
        with self.assertRaisesRegex(TransferError,'Claw position'):trial.review(self.s,PARAMS)
        self.assertEqual(self.s.robot.jobs,[])

    def test_explicit_replay_preserves_previous_record(self):
        first=trial.review(self.s,PARAMS);trial.execute(self.run,self.s,PARAMS,first)
        original=self.output.read_bytes();reference=hashlib.sha256(original).hexdigest()
        replay=self.output.with_name('loaded_roundtrip_137_replay_test.json')
        plan=trial.review(self.s,PARAMS,replay,reference)
        self.assertTrue(trial.execute(self.run,self.s,PARAMS,plan,replay,reference)['ok'])
        self.assertEqual(self.output.read_bytes(),original)
        with self.assertRaisesRegex(TransferError,'latest completed'):
            trial.review(self.s,PARAMS,self.output.with_name('another.json'),reference)

    def test_stopped_program_never_auto_starts(self):
        self.s.robot.program_state='stopped'
        with self.assertRaisesRegex(TransferError,'Already-running'):trial.review(self.s,PARAMS)
        self.assertEqual(self.s.robot.jobs,[])

    def test_stop_before_first_stage(self):
        plan=trial.review(self.s,PARAMS);self.run.cancelled=True
        with self.assertRaises(TransferError):trial.execute(self.run,self.s,PARAMS,plan)
        self.assertEqual(self.s.robot.jobs,[]);self.assertEqual(self.s.moves,[])

    def test_wrong_start_and_old_queue_refused(self):
        self.s.pose['X']+=1
        with self.assertRaisesRegex(TransferError,'differs'):trial.review(self.s,PARAMS)
        self.s.pose['X']-=1;self.s.robot.vars[17]=220107
        with self.assertRaisesRegex(TransferError,'speed-137'):trial.review(self.s,PARAMS)

    def test_claw_change_during_queue_stops_without_next_stage(self):
        plan=trial.review(self.s,PARAMS)
        move=self.s.robot.lua.globals().MoveL
        def changed(*args):
            move(*args);self.e1=3.6
        self.s.robot.lua.globals().MoveL=changed
        with self.assertRaisesRegex(TransferError,'Claw position'):
            trial.execute(self.run,self.s,PARAMS,plan)
        self.assertEqual(self.s.robot.program_state,'stopped')
        self.assertEqual(self.s.moves,[])
        self.assertEqual(self.s.grips,[])

if __name__=='__main__':unittest.main()
