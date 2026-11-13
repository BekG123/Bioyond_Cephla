"""Offline tests for rack-aware IDLE turning; no hardware access."""
import unittest
from unittest.mock import patch

from autonomy import TransferError, ALIGN_WRIST_STEP_DEG, wrap
from idle_pivot import reference, stages_for_idle
from researcher_home import queued_station_stages
from hamilton_rack_clearance import route, Z77_PROFILES
from hamilton_empty_clearance import IDLE_JOINTS
from plan_short_side_hamilton import validate


class IdlePivotTests(unittest.TestCase):
    def setUp(self):
        self.d=reference();self.target=self.d['idle'];self.cfg=self.d['config']
        self.env={k:(self.d['envelope'][k]['min'],self.d['envelope'][k]['max']) for k in ('X','Y','Z')}

    def inspect(self,start,q):
        stages=queued_station_stages(start,self.target,q,self.cfg,self.env)
        current=dict(start);points=[];turn_seen=False;turns=0
        for stage in stages:
            if stage['kind']=='rotate':
                turns+=1;turn_seen=True
                for k in ('X','Y','Z'):self.assertAlmostEqual(current[k],self.d['commanded_pivot'][k],places=5)
                self.assertTrue(stage['queued_pivot'])
                self.assertLessEqual(abs(wrap(stage['rz']-current['Rz'])),180)
                chunk=[dict(current,Rz=stage['rz'])]
            else:
                chunk=stage['points']
                for point in chunk:
                    yaw=self.target['Rz'] if turn_seen else start['Rz']
                    self.assertLess(abs(wrap(point['Rz']-yaw)),.01)
            points+=chunk;current=chunk[-1]
        self.assertEqual(turns,1)
        self.assertEqual(current,self.target)
        checked=validate(start,points,q,self.cfg,self.env,IDLE_JOINTS)
        self.assertTrue(checked['workspace_valid'])
        return stages

    def test_current_taught_pose_turns_at_pivot_before_idle(self):
        self.inspect(self.d['pose_mm'],self.d['joints'])

    def test_home_clearance_translates_to_pivot_before_any_wrist_turn(self):
        r,q=route(Z77_PROFILES[1]);stages=self.inspect(r['start'],q)
        self.assertEqual(len(stages[0]['points']),2)
        self.assertEqual(stages[0]['points'][-1]['Y'],45.61)

    def test_high_start_lowers_only_at_pivot(self):
        start=dict(self.d['pose_mm'],X=315,Y=10,Z=320)
        from autonomy import check_path
        q=check_path(self.d['pose_mm'],start,self.d['joints'],self.cfg,self.env)
        q['J1']=self.d['joints']['J1']+start['Z']-self.d['pose_mm']['Z']
        stages=self.inspect(start,q)
        self.assertEqual(stages[0]['points'][0]['Z'],320)
        self.assertEqual(stages[0]['points'][-1]['Z'],300)

    def test_changed_reference_and_unreachable_start_do_not_fall_back(self):
        with patch('idle_pivot.REFERENCE_SHA','invalid'),self.assertRaises(TransferError):
            queued_station_stages(self.d['pose_mm'],self.target,self.d['joints'],self.cfg,self.env)
        with self.assertRaises(TransferError):
            queued_station_stages(dict(self.d['pose_mm'],X=900),self.target,self.d['joints'],self.cfg,self.env)

    def test_other_targets_and_no_turn_needed_keep_existing_planner(self):
        self.assertIsNone(stages_for_idle(self.d['pose_mm'],dict(self.target,X=300),self.d['joints'],self.cfg,self.env))
        self.assertIsNone(stages_for_idle(dict(self.d['pose_mm'],Rz=-3.88),self.target,self.d['joints'],self.cfg,self.env))

    def test_real_lua_uses_one_command_and_one_completion_barrier(self):
        from test_short_side_hover_transfer import HoverTransferTests
        from trajectory_queue import LuaTrajectory
        from autonomy import check_path
        helper=HoverTransferTests();helper.setup_route();s=helper.s
        from build_pivot_joint_program import candidate_lua
        from test_trajectory_queue import Controller
        from pathlib import Path
        s.robot=Controller(s,source=candidate_lua((Path(__file__).resolve().parents[1]/'lua/mod_Trajectory_segment_speeds.lua').read_text()))
        s.pose=dict(self.d['commanded_pivot'],Rz=84.17)
        s.q=check_path(self.d['pose_mm'],s.pose,self.d['joints'],self.cfg,self.env)
        s.q['J1']=self.d['joints']['J1']+300-self.d['pose_mm']['Z']
        end=dict(s.pose,Rz=-3.88)
        result=LuaTrajectory(s).execute(helper.run,s.pose,s.q,[end],self.cfg,137,lambda *a:None,
                                        reviewed=True,idle_pivot_rotation=True)
        self.assertTrue(result['ok']);self.assertEqual(len(s.robot.calls),1)
        self.assertEqual(s.robot.calls[0][1],137);self.assertEqual(s.robot.barriers,1)
        self.assertEqual(s.robot.motion_kinds,['MoveJ'])
        self.assertEqual(s.robot.calls[0][0][6:9],(3.4,-2,0));self.assertEqual(s.grips,[])

    def test_queue_rejects_wrong_pivot_translation_multiple_points_and_speed(self):
        from trajectory_queue import prepare_points,LuaTrajectory
        from test_short_side_hover_transfer import HoverTransferTests
        start=dict(self.d['commanded_pivot'],Rz=84.17);end=dict(start,Rz=-3.88)
        for initial,points in [(dict(start,X=306.2),[end]),(start,[dict(end,X=end['X']+.1)]),(start,[end,end])]:
            with self.assertRaises(TransferError):
                prepare_points(initial,self.d['joints'],points,self.cfg,reviewed=True,idle_pivot_rotation=True)
        helper=HoverTransferTests();helper.setup_route()
        with self.assertRaises(TransferError):
            LuaTrajectory(helper.s).execute(helper.run,start,self.d['joints'],[end],self.cfg,138,lambda *a:None,
                                            reviewed=True,idle_pivot_rotation=True)
        self.assertEqual(helper.s.robot.jobs,[])


if __name__=='__main__':unittest.main()
