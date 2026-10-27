"""Pure route diagnostics; no robot or camera connection."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
from researcher import register_researcher
from researcher_routine_check import check_routine
from test_transfer import PARAMS, ENVELOPE


class RoutineCheckTests(unittest.TestCase):
    def setUp(self):
        self.routine = dict(id='saved', revision=7, reviewed=True, frame=dict(tool='T0',user='U0'), waypoints=[])
        for name,z in [('Home',248),('Calibrate',286),('Align',300),('Descend',100),('Grip',100),('Hamilton',100)]:
            self.routine['waypoints'].append(dict(station=name, source='robot_controller',
                pose_mm=dict(X=326.,Y=0.,Z=z,Rz=0.), joints=dict(J1=z-38.6,J2=60.,J3=60.,J4=-120.),
                gripper=dict(E1=28 if name=='Descend' else 3)))

    def check(self, envelope=ENVELOPE, enabled=True):
        return check_routine(self.routine, PARAMS, envelope, enabled)

    def test_valid_geometry_is_not_execution_authorization(self):
        original=copy.deepcopy(self.routine)
        report=self.check()
        self.assertTrue(report['checks_passed'], report['issues'])
        self.assertFalse(report['execution_ready'])
        self.assertEqual(report['hardware_commands_sent'],0)
        self.assertTrue(all(r['valid'] for r in report['routes']))
        self.assertEqual(self.routine,original)

    def test_actual_hamilton_limit_violations_collected_together(self):
        self.routine['waypoints'][-1]['pose_mm']=dict(X=175.629,Y=-386.510,Z=36.231,Rz=-5.316)
        report=self.check(dict(X=(200,450),Y=(-250,100),Z=(70,400)))
        codes=[i['code'] for i in report['issues']]
        self.assertIn('workspace',codes)
        self.assertIn('reach',codes)
        self.assertEqual(codes.count('route'),2)
        self.assertFalse(report['checks_passed'])

    def test_partial_descent_and_opening_are_not_silently_reinterpreted(self):
        self.routine['waypoints'][3]['pose_mm']['Z']=278.459
        self.routine['waypoints'][4]['pose_mm']['Z']=72.139
        self.routine['waypoints'][3]['gripper']['E1']=.000186
        self.routine['waypoints'][4]['gripper']['E1']=3.57923
        codes={i['code'] for i in self.check()['issues']}
        self.assertTrue({'pickup_depth','grip_direction'} <= codes)

    def test_missing_measurements_and_wrong_frame_block(self):
        del self.routine['waypoints'][0]['joints']
        self.routine['frame']['tool']='T1'
        codes={i['code'] for i in self.check()['issues']}
        self.assertTrue({'measurement','frame'} <= codes)

    def test_disabled_workspace_and_intermediate_route_are_explicit(self):
        self.routine['waypoints'].insert(-1,dict(station='Waypoint'))
        codes={i['code'] for i in self.check(enabled=False)['issues']}
        self.assertTrue({'workspace_disabled','intermediate'} <= codes)

    def test_route_keeps_wrist_limits(self):
        self.routine['waypoints'][-1]['pose_mm']['Rz']=-100
        self.assertTrue(any(i['code']=='route' and 'J4' in i['message'] for i in self.check()['issues']))

    def test_get_route_only_reads_saved_data(self):
        app=Flask(__name__)
        teaching=Mock()
        teaching.export.return_value=self.routine
        read_state=Mock(side_effect=AssertionError('No live state needed'))
        register_researcher(app,read_state,teaching,
            routine_check=lambda r:check_routine(r,PARAMS,ENVELOPE,True))
        response=app.test_client().get('/researcher/api/routines/saved/check')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['checks_passed'])
        teaching.export.assert_called_once_with('saved')
        self.assertEqual(len(teaching.mock_calls),1)
        read_state.assert_not_called()


if __name__=='__main__': unittest.main()
