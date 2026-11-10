import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from short_side_alignment_trial import reference,reference_for_candidate,validate_route,candidate_points
from trajectory_queue import prepare_points, LuaTrajectory

class PinnedRoute(unittest.TestCase):
    def setUp(self):
        self.plan,self.taught=reference()
        self.env={k:(self.taught['envelope'][k]['min'],self.taught['envelope'][k]['max']) for k in ('X','Y','Z')}
    def check(self,points=None,cfg=None,envelope=None,joints=None):
        return validate_route(self.plan['home'],points or self.plan['candidates']['direct']['points'],joints or self.plan['home_joints'],cfg or self.taught['config'],envelope or self.env,'direct')
    def test_saved_route_reaches_taught_winding(self):
        q=self.check()
        for key in ('J2','J3','J4'):self.assertLess(abs(q[key]-self.taught['taught_joints'][key]),.5)
    def test_point_edit_and_joint_winding_are_rejected(self):
        points=copy.deepcopy(self.plan['candidates']['direct']['points']);points[-1]['Z']-=1
        with self.assertRaises(ValueError):self.check(points=points)
        q=dict(self.plan['home_joints']);q['J4']+=360
        with self.assertRaises(ValueError):self.check(joints=q)
    def test_envelope_or_ik_changes_are_rejected(self):
        env=dict(self.env);env['Z']=(0,400)
        with self.assertRaises(ValueError):self.check(envelope=env)
        cfg=dict(self.taught['config']);cfg['j4_hard_abs_deg']=280
        with self.assertRaises(ValueError):self.check(cfg=cfg)

    def test_single_motion_validates_whole_route_and_keeps_default_limits(self):
        p=candidate_points(self.plan,'smooth_direct')
        q=validate_route(self.plan['home'],p,self.plan['home_joints'],self.taught['config'],self.env,'smooth_direct')
        self.assertLess(abs(q['J4']-self.taught['taught_joints']['J4']),.5)
        args=(self.plan['home'],self.plan['home_joints'],p,self.taught['config'])
        with self.assertRaises(ValueError):prepare_points(*args,reviewed=True)
        result,_=prepare_points(*args,reviewed=True,short_side_alignment='smooth_direct')
        self.assertEqual(result,p)
        for kw in ({'reviewed':False},{'reviewed':True,'home_transit':True}):
            with self.assertRaises(ValueError):prepare_points(*args,short_side_alignment='smooth_direct',**kw)
        p[0]['X']+=.01
        with self.assertRaises(ValueError):prepare_points(*args,reviewed=True,short_side_alignment='smooth_direct')

    def test_single_motion_real_lua_serialization(self):
        from test_transfer import FakeService
        from test_trajectory_queue import Controller
        from test_researcher_workflow import FakeRunner
        s=FakeService();s.pose=dict(self.plan['home']);s.q=dict(self.plan['home_joints'])
        s.cfg=self.taught['config'];s.envelope=self.env
        s.robot=Controller(s);s._locked=lambda fn:fn()
        run=FakeRunner();run.cancelled=False
        result=LuaTrajectory(s).execute(run,s.pose.copy(),s.q.copy(),candidate_points(self.plan,'smooth_direct'),s.cfg,137,lambda *args:None,reviewed=True,short_side_alignment='smooth_direct')
        self.assertTrue(result['ok'])
        self.assertEqual(len(s.robot.calls),1)
        self.assertEqual(s.robot.barriers,1)
        self.assertEqual(s.robot.calls[0][1:3],(137,-1))
        self.assertEqual(s.robot.calls[0][0][6:9],(3.4,-2,0))

    def test_corrected_alignment_and_descent_real_lua(self):
        from test_transfer import FakeService
        from test_trajectory_queue import Controller
        from test_researcher_workflow import FakeRunner
        plan,taught=reference_for_candidate('corrected02');points=candidate_points(plan,'corrected02')
        self.assertEqual(len(points),2)
        self.assertAlmostEqual(points[0]['Z']-points[1]['Z'],30)
        for k in ('X','Y','Rz'):self.assertEqual(points[0][k],points[1][k])
        s=FakeService();s.pose=dict(plan['home']);s.q=dict(plan['home_joints']);s.cfg=taught['config']
        s.envelope={k:(taught['envelope'][k]['min'],taught['envelope'][k]['max']) for k in ('X','Y','Z')}
        s.robot=Controller(s);s._locked=lambda fn:fn()
        run=FakeRunner();run.cancelled=False
        result=LuaTrajectory(s).execute(run,s.pose.copy(),s.q.copy(),points,s.cfg,137,lambda *args:None,reviewed=True,short_side_alignment='corrected02')
        self.assertTrue(result['ok']);self.assertEqual(len(s.robot.calls),2);self.assertEqual(s.robot.barriers,1)
        self.assertEqual([c[1] for c in s.robot.calls],[137,137])
        for call in s.robot.calls:self.assertEqual(call[0][6:9],(3.4,-2,0))
        altered=copy.deepcopy(points);altered[-1]['Z']-=1
        with self.assertRaises(ValueError):validate_route(plan['home'],altered,plan['home_joints'],s.cfg,s.envelope,'corrected02')

if __name__=='__main__':unittest.main()
