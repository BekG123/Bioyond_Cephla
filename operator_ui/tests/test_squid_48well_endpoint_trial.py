"""New endpoint through real Lua with fake motion; never connects hardware."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import squid_48well_endpoint_trial as trial
from scope_compact137 import accepted
from sequences import get_robot_params
from trajectory_queue import LuaTrajectory,prepare_points
from test_transfer import FakeService
from test_trajectory_queue import Controller
from test_researcher_workflow import FakeRunner

class EndpointTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        p=patch.object(trial,'OUTPUT',Path(tmp.name)/'trial.json');p.start();self.addCleanup(p.stop)
        plan,self.path=trial.reference();_,_,_,prior=accepted()
        self.s=FakeService();self.cfg=get_robot_params();self.s.cfg=self.cfg
        self.s.pose=dict(self.path[0]);self.s.q=dict(prior['reverse']['final_robot']['joints'])
        self.s.envelope=plan['envelope'];self.e1=3.9;self.stops=[]
        self.s.external_axes=lambda:dict(E1=self.e1)
        self.s.status=lambda:dict(ok=True,connected=True,errors=[],enabled=True,
            control_mode={'mode':'auto'},program_state={'state':self.s.robot.program_state},
            pose_mm=self.s.pose_mm(),joints=self.s.joints(),external_axes=self.s.external_axes())
        self.s._locked=lambda fn:fn();self.s.robot=Controller(self.s)
        self.s.program=self.stop;self.run=FakeRunner();self.run.cancelled=False
    def stop(self,action):
        self.stops.append(action);self.s.robot.program_state='stopped';self.s.robot.released.set()
        return dict(ok=True)
    def test_exact_route_and_speed_without_gripper_commands(self):
        approved=trial.review(self.s,self.cfg);result=trial.execute(self.run,self.s,self.cfg,approved)
        self.assertTrue(result['ok']);self.assertTrue(result['seating_inspection_required'])
        self.assertEqual([c[1] for c in self.s.robot.calls],[137,137,137,5])
        self.assertTrue(result['clearance_checkpoint'])
        self.assertEqual(self.path[-1]['Z'],270.)
        self.assertEqual(self.s.grips,[]);self.assertEqual(self.stops,[])
        trial.near(self.s.pose,self.path[-1],.001)
        self.assertEqual(json.loads(trial.OUTPUT.read_text())['status'],'motion_completed_awaiting_seating_inspection')
        with self.assertRaisesRegex(Exception,'already attempted'):trial.review(self.s,self.cfg)
    def test_mutated_route_unreviewed_or_mixed_profile_rejected(self):
        bad=[dict(p) for p in self.path[1:]];bad[-1]['X']+=.01
        for points,kwargs in [(bad,dict(reviewed=True,scope_trial=True)),
                (self.path[1:],dict(scope_trial=True)),
                (self.path[1:],dict(reviewed=True,scope_trial=True,scope_compact=True))]:
            with self.assertRaises(Exception):prepare_points(self.path[0],self.s.q,points,self.cfg,**kwargs)
        self.assertEqual(self.s.robot.jobs,[])
    def test_descent_overspeed_rejected_before_dispatch(self):
        with self.assertRaisesRegex(Exception,'at most 10'):
            LuaTrajectory(self.s).execute(self.run,self.path[-2],self.s.q,self.path[-1:],self.cfg,137,
                lambda *a:None,reviewed=True,scope_trial=True,scope_speed137=True,scope_phase='descent')
        self.assertEqual(self.s.robot.jobs,[])
    def test_old_endpoint_not_accepted_by_new_trial(self):
        _,old,_,_=accepted()
        with self.assertRaises(Exception):trial.validate_route(old[0],old[1:])
    def test_changed_grip_stops_before_descent(self):
        approved=trial.review(self.s,self.cfg);original=self.s.robot.finish
        def finish():original();self.e1+=.2
        self.s.robot.finish=finish;self.s.robot.lua.globals().MOVFINISH=finish
        with self.assertRaisesRegex(Exception,'Gripper'):trial.execute(self.run,self.s,self.cfg,approved)
        self.assertEqual(len(self.s.robot.calls),3);self.assertIn('stop',self.stops)
    def test_stopped_run_does_not_move(self):
        approved=trial.review(self.s,self.cfg);self.run.cancelled=True
        with self.assertRaisesRegex(Exception,'Stopped'):trial.execute(self.run,self.s,self.cfg,approved)
        self.assertEqual(self.s.robot.calls,[])
    def test_changed_limits_and_grip_rejected(self):
        cfg=dict(self.cfg);cfg['j2_margin_deg']=1
        with self.assertRaisesRegex(Exception,'limits'):trial.review(self.s,cfg)
        self.e1=3.7
        with self.assertRaisesRegex(Exception,'3.9'):trial.review(self.s,self.cfg)

if __name__=='__main__':unittest.main()
