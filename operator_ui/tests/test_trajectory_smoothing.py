"""Bounded grouping tests; real Lua execution uses fake vendor functions only."""
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from autonomy import TransferError,check_path,wrap
from trajectory_queue import LuaTrajectory,prepare_points,KEYS
from trajectory_smoothing import group_points,span_error
from recorded_return import RecordedReturn
from test_transfer import FakeService,PARAMS
from test_researcher_workflow import FakeRunner
from test_trajectory_queue import Controller

HERE=Path(__file__).resolve().parents[1]


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.s=FakeService()
        self.start=self.s.pose.copy()
        self.q=self.s.q.copy()

    def test_straight_motion_is_grouped_without_changing_end_or_input(self):
        points=[{**self.start,'Y':i} for i in range(1,61)]
        original=json.dumps(points)
        grouped,q,report=group_points(self.start,self.q,points,PARAMS)
        self.assertEqual(json.dumps(points),original)
        self.assertEqual(grouped[-1],points[-1])
        self.assertLess(len(grouped),25)
        self.assertAlmostEqual(report['max_position_error_mm'],0)
        self.assertEqual(report['max_yaw_error_deg'],0)
        self.assertEqual(grouped[:5],points[:5])
        self.assertEqual(grouped[-10:],points[-10:])

    def test_near_collinear_vertex_deviation_is_bounded(self):
        a=dict(X=0,Y=0,Z=0,Rz=0)
        self.assertIsNotNone(span_error([a,dict(X=5,Y=.2,Z=0,Rz=.05),dict(X=10,Y=0,Z=0,Rz=0)],0,2))
        self.assertIsNone(span_error([a,dict(X=5,Y=.26,Z=0,Rz=0),dict(X=10,Y=0,Z=0,Rz=0)],0,2))
        self.assertIsNone(span_error([a,dict(X=5,Y=0,Z=0,Rz=.11),dict(X=10,Y=0,Z=0,Rz=0)],0,2))

    def test_collinear_reversal_is_not_shortcut(self):
        points=[dict(X=x,Y=0,Z=0,Rz=0) for x in (0,5,3,10)]
        self.assertIsNone(span_error(points,0,3))

    def test_stationary_yaw_reversal_is_not_shortcut(self):
        points=[dict(X=0,Y=0,Z=0,Rz=y) for y in (0,5,3,10)]
        self.assertIsNone(span_error(points,0,3))

    def test_wrapped_yaw_has_a_short_continuous_correspondence(self):
        points=[dict(X=x,Y=0,Z=0,Rz=y) for x,y in [(0,179),(1,180),(2,-179)]]
        for error in span_error(points,0,2):self.assertAlmostEqual(error,0)

    def test_sharp_turn_and_reversal_are_preserved(self):
        points=[{**self.start,'Y':i} for i in range(1,21)]
        points += [{**self.start,'X':self.start['X']+i,'Y':20} for i in range(1,21)]
        points += [{**self.start,'X':self.start['X']+20-i,'Y':20} for i in range(1,21)]
        grouped,_,report=group_points(self.start,self.q,points,PARAMS)
        self.assertIn(points[19],grouped)
        self.assertIn(points[39],grouped)

    def test_unsafe_combined_kinematics_falls_back_to_original_segments(self):
        points=[{**self.start,'Y':i} for i in range(1,31)]
        def guard(a,b,q,cfg,box):
            if b['Y']-a['Y']>1.01:raise TransferError('synthetic interior joint limit')
            return q
        with patch('trajectory_smoothing.check_path',side_effect=guard):
            grouped,_,_=group_points(self.start,self.q,points,PARAMS)
        self.assertEqual(grouped,points)

    def test_real_recording_grouped_both_directions_and_executed_through_lua(self):
        path=HERE/'demonstrations/return_home_20261016_130748/return_path.json'
        if not path.exists():self.skipTest('Local demonstration not present')
        data=json.loads(path.read_bytes())
        cfg=json.loads((HERE/'robot_params.json').read_text())
        for direction in ('to_hamilton','toward_home'):
            directed=RecordedReturn.directed(data,direction)
            first=directed['trajectory'][0]
            service=FakeService()
            service.cfg=cfg
            service.pose=first['pose_mm'].copy()
            service.q=first['joints'].copy()
            service.robot=Controller(service)
            service._locked=lambda fn:fn()
            service.program=Mock(return_value={'ok':True})
            run=FakeRunner()
            run.cancelled=False
            replay=RecordedReturn(path.parent,lambda:service,lambda:run,lambda:cfg,Mock(),Mock())
            legs,_=replay.plan(directed)
            points,_=prepare_points(service.pose,service.q,legs,cfg)
            vertices=[service.pose]+points
            grouped,expected,report=group_points(service.pose,service.q,points,cfg)
            self.assertEqual(report['output_points'],132)
            self.assertEqual(grouped[-1],points[-1])
            self.assertLessEqual(report['max_position_error_mm'],.25)
            self.assertLessEqual(report['max_yaw_error_deg'],.1)
            self.assertTrue(set(report['protected_vertices']) <= {0}|{g['last'] for g in report['groups']})
            for group in report['groups']:
                a,b=vertices[group['first']],vertices[group['last']]
                self.assertLessEqual(math.dist([a[k] for k in KEYS[:3]],[b[k] for k in KEYS[:3]]),50.001)
                self.assertLessEqual(abs(wrap(b['Rz']-a['Rz'])),10.001)
                self.assertIsNotNone(span_error(vertices,group['first'],group['last']))
            result=LuaTrajectory(service).execute(run,service.pose.copy(),service.q.copy(),legs,cfg,40,Mock(),grouped=True)
            self.assertTrue(result['ok'])
            self.assertEqual(len(service.robot.calls),132)
            self.assertEqual(service.robot.barriers,1)
            self.assertEqual(result['grouping']['output_points'],132)
            self.assertEqual(len([j for j in service.robot.jobs if j[4]==2]),44)
            service.program.assert_not_called()


if __name__=='__main__':unittest.main()
