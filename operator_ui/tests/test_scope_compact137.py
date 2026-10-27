"""Exact scope round trip through real Lua with fake vendor motion only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scope_compact137 as trial
from test_transfer import FakeService
from test_trajectory_queue import Controller
from test_researcher_workflow import FakeRunner
from sequences import get_robot_params
from trajectory_queue import LuaTrajectory


class Scope137Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(trial,'OUTPUT',Path(self.temp.name)/'roundtrip.json');p.start();self.addCleanup(p.stop)
        plan,self.path,_,baselines=trial.accepted()
        self.s=FakeService();self.cfg=get_robot_params();self.s.cfg=self.cfg
        self.s.pose=dict(baselines['forward']['final_robot']['pose_mm'])
        self.s.q=dict(baselines['forward']['final_robot']['joints'])
        self.s.envelope=plan['envelope'];self.e1=3.7034;self.stops=[]
        self.s.external_axes=lambda:dict(E1=self.e1)
        self.s.status=lambda:dict(ok=True,connected=True,errors=[],enabled=True,control_mode={'mode':'auto'},program_state={'state':self.s.robot.program_state},pose_mm=self.s.pose_mm(),joints=self.s.joints())
        self.s._locked=lambda fn:fn();self.s.robot=Controller(self.s)
        self.s.program=self.stop;self.run=FakeRunner();self.run.cancelled=False

    def stop(self,action):
        self.stops.append(action);self.s.robot.program_state='stopped';self.s.robot.released.set()
        return dict(ok=True)

    def test_roundtrip_eight_exact_points_speed137(self):
        approved=trial.review(self.s,self.cfg)
        result=trial.execute(self.run,self.s,self.cfg,approved)
        self.assertTrue(result['ok']);self.assertEqual(len(self.s.robot.calls),8)
        self.assertEqual(self.s.robot.barriers,2)
        expected=list(reversed(self.path))[1:]+self.path[1:]
        actual=[dict(zip(('X','Y','Z','Rz'),t[:3]+(t[5],))) for t,*_ in self.s.robot.calls]
        for a,b in zip(actual,expected):trial.near(a,b,.001)
        self.assertTrue(all(c[1:]==(137,-1,'T0','U0') for c in self.s.robot.calls))
        self.assertTrue(all(c[0][6:]==(3.4,-2,0,0,0,0) for c in self.s.robot.calls))
        self.assertEqual(self.s.grips,[]);self.assertEqual(self.stops,[])
        trial.near(self.s.pose,self.path[-1],.001)
        self.assertEqual(json.loads(trial.OUTPUT.read_text())['status'],'completed')
        with self.assertRaisesRegex(Exception,'already attempted'):trial.review(self.s,self.cfg)

    def test_route_mutation_unreviewed_overspeed_and_mixed_profile_rejected(self):
        route=list(reversed(self.path));bad=[dict(p) for p in route[1:]];bad[1]['X']+=1
        for points,speed,kwargs in [(bad,137,dict(reviewed=True,scope_compact=True,scope_speed137=True)),
                (route[1:],138,dict(reviewed=True,scope_compact=True,scope_speed137=True)),
                (route[1:],137,dict(scope_compact=True,scope_speed137=True)),
                (route[1:],137,dict(reviewed=True,scope_compact=True,scope_speed137=True,home_transit=True))]:
            with self.assertRaises(Exception):LuaTrajectory(self.s).execute(self.run,route[0],self.s.q,points,self.cfg,speed,lambda *a:None,**kwargs)
        self.assertEqual(self.s.robot.jobs,[])

    def test_stop_prevents_any_dispatch(self):
        plan=trial.review(self.s,self.cfg);self.run.cancelled=True
        with self.assertRaisesRegex(Exception,'Stopped'):trial.execute(self.run,self.s,self.cfg,plan)
        self.assertEqual(self.s.robot.calls,[])

    def test_pickup_departure_preserves_four_reverse_targets(self):
        route=list(reversed(self.path))
        start={**route[0], 'Z':route[0]['Z']+5}
        self.s.pose=dict(start);self.s.q['J1']+=5
        result=LuaTrajectory(self.s).execute(
            self.run,start,self.s.q,route[1:],self.cfg,137,lambda *a:None,
            reviewed=True,scope_compact=True,scope_speed137=True)
        self.assertTrue(result['ok'])
        self.assertEqual(len(self.s.robot.calls),4)
        trial.near(self.s.pose,self.path[0],.001)
        self.assertEqual(self.s.grips,[])

    def test_pickup_departure_rejects_sideways_yaw_or_excess_height(self):
        points=list(reversed(self.path))[1:]
        start={**self.path[-1], 'Z':self.path[-1]['Z']+5}
        for axis,delta in [('X',.3),('Y',.3),('Rz',.3),('Z',1)]:
            with self.assertRaises(Exception):
                trial.validate_route({**start,axis:start[axis]+delta},points)

    def test_gripper_change_between_legs_stops_return(self):
        plan=trial.review(self.s,self.cfg);original=self.s.robot.finish
        def finish():original();self.e1+=.2
        self.s.robot.finish=finish
        self.s.robot.lua.globals().MOVFINISH=finish
        with self.assertRaisesRegex(Exception,'Gripper'):trial.execute(self.run,self.s,self.cfg,plan)
        self.assertEqual(len(self.s.robot.calls),4)
        self.assertIn('stop',self.stops)

    def test_winding_and_missing_protocol_refuse(self):
        self.s.q['J4']+=360
        with self.assertRaisesRegex(Exception,'winding'):trial.review(self.s,self.cfg)
        self.s.q['J4']-=360;self.s.robot.vars[17]=220101
        with self.assertRaisesRegex(Exception,'speed-137'):trial.review(self.s,self.cfg)
        self.assertEqual(self.s.robot.calls,[])

    def test_unconfirmed_first_leg_stops_without_second_leg(self):
        plan=trial.review(self.s,self.cfg);original=self.s.robot.set_sys_var_i
        def reply(values,reply_timeout=10):
            result=original(values,reply_timeout)
            return None if values.get(4)==4 else result
        self.s.robot.set_sys_var_i=reply
        with self.assertRaisesRegex(Exception,'unconfirmed'):trial.execute(self.run,self.s,self.cfg,plan)
        self.assertEqual(len(self.s.robot.calls),4);self.assertIn('stop',self.stops)

    def production_start(self):
        _,_,_,baselines=trial.accepted()
        self.s.pose=dict(self.path[0])
        self.s.q=dict(baselines['reverse']['final_robot']['joints'])

    def test_production_only_slows_final_descent_and_reverse_stays137(self):
        self.production_start()
        result=trial.execute_route(self.run,self.s,self.s.pose_mm(),self.s.joints(),
                                   self.path[1:],self.cfg,lambda *args:None)
        self.assertTrue(result['ok'])
        self.assertEqual([c[1] for c in self.s.robot.calls],[137,137,137,10])
        self.assertEqual(self.s.robot.barriers,2)
        expected=self.path[1:]
        actual=[dict(zip(('X','Y','Z','Rz'),t[:3]+(t[5],))) for t,*_ in self.s.robot.calls]
        for a,b in zip(actual,expected):trial.near(a,b,.001)
        result=trial.execute_route(self.run,self.s,self.s.pose_mm(),self.s.joints(),
                                   list(reversed(self.path))[1:],self.cfg,lambda *args:None)
        self.assertTrue(result['ok'])
        self.assertEqual([c[1] for c in self.s.robot.calls],[137,137,137,10]+[137]*4)
        self.assertEqual(self.s.grips,[])

    def test_production_uncertain_transit_never_starts_descent(self):
        self.production_start()
        original=self.s.robot.set_sys_var_i
        def reply(values,reply_timeout=10):
            result=original(values,reply_timeout)
            return None if values.get(4)==4 else result
        self.s.robot.set_sys_var_i=reply
        with self.assertRaisesRegex(Exception,'unconfirmed'):
            trial.execute_route(self.run,self.s,self.s.pose_mm(),self.s.joints(),
                                self.path[1:],self.cfg,lambda *args:None)
        self.assertEqual(len(self.s.robot.calls),3)
        self.assertIn('stop',self.stops)

    def test_production_stop_or_changed_grip_prevents_descent(self):
        for fault in ('stop','grip'):
            with self.subTest(fault=fault):
                self.production_start()
                self.run.cancelled=False
                self.e1=3.7
                self.s.robot=Controller(self.s)
                original=self.s.robot.finish
                def finish():
                    original()
                    if fault=='stop':self.run.cancelled=True
                    else:self.e1=5
                self.s.robot.lua.globals().MOVFINISH=finish
                holding=trial.HoldingService(self.s,3.7,self.s.envelope)
                with self.assertRaises(Exception):
                    trial.execute_route(self.run,holding,self.s.pose_mm(),self.s.joints(),
                                        self.path[1:],self.cfg,lambda *args:None)
                self.assertEqual(len(self.s.robot.calls),3)

    def test_descent_phase_rejects_overspeed_or_changed_geometry(self):
        for speed,points in ((11,[self.path[-1]]), (40,[self.path[-1]]),
                             (10,[{**self.path[-1],'X':self.path[-1]['X']+1}])):
            with self.assertRaises(Exception):
                LuaTrajectory(self.s).execute(self.run,self.path[-2],self.s.q,points,
                    self.cfg,speed,lambda *a:None,reviewed=True,scope_compact=True,
                    scope_speed137=True,scope_phase='descent')
        self.assertEqual(self.s.robot.jobs,[])


if __name__=='__main__':unittest.main()
