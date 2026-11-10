"""Exercise the real wrist service offline at the failed Home boundary."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI))
from robot_service import RobotService, PF_RZ, PF_X, PF_Y, PF_Z, MOVETYPE_JOINT
from researcher_home import queued_station_stages, rotate_home_wrist
from straight_transfer import validate_home_transit
from autonomy import TransferError


class WristCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.pose = dict(X=279.33, Y=26.38, Z=300., Rz=-3.9)
        self.service = RobotService()
        self.service._locked = lambda function: function()
        self.service.pose_mm = lambda: deepcopy(self.pose)
        self.commands = []
        self.arrives = True
        def hostpoint(fields, mode, timeout):
            self.commands.append((fields, mode))
            if self.arrives:
                self.pose['Rz'] = fields[PF_RZ]
            return {'ok':True}
        self.service._hostpoint = hostpoint
        self.guard = Mock(service=self.service)
        self.guard.rotate_to_rz.side_effect = lambda yaw: self.service.rotate_to_rz(
            yaw, speed=30, force_delta=yaw-self.pose['Rz'])
        self.cfg = json.loads((UI/'robot_params.json').read_bytes())
        self.env = dict(X=(200,450),Y=(-250,380),Z=(70,400))
        self.home = dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
        self.joints = dict(J1=261.401,J2=76.872,J3=45.78,J4=-126.552)

    def test_small_explicit_rotation_is_sent_without_translation(self):
        before = dict(self.pose)
        rotate_home_wrist(self.guard, -3.88)
        self.assertEqual(len(self.commands), 1)
        fields, mode = self.commands[0]
        self.assertEqual(mode, MOVETYPE_JOINT)
        self.assertEqual([fields[k] for k in (PF_X,PF_Y,PF_Z)], [before[k] for k in ('X','Y','Z')])
        validate_home_transit(self.pose, [dict(self.home,Z=300),self.home])

    def test_missing_wrist_motion_is_rejected_before_translation(self):
        self.arrives = False
        with self.assertRaisesRegex(TransferError, 'did not settle'):
            rotate_home_wrist(self.guard, -3.88)
        self.assertEqual(len(self.commands), 1)

    def test_planner_includes_small_rotation_after_clearance_lift(self):
        for yaw in (-3.905,-3.9,-3.899):
            with self.subTest(yaw=yaw):
                start = dict(self.pose,Z=289.121,Rz=yaw)
                stages = queued_station_stages(start,self.home,self.joints,self.cfg,self.env)
                self.assertEqual([s['kind'] for s in stages], ['queue','rotate','queue'])
                self.assertEqual(stages[0]['points'][-1]['Z'],300)
                self.assertAlmostEqual(stages[1]['rz'],-3.88)
                current = dict(start)
                for stage in stages:
                    if stage['kind'] == 'rotate':
                        current['Rz'] = stage['rz']
                    else:
                        validate_home_transit(current,stage['points'])
                        current = stage['points'][-1]
                self.assertEqual(current,self.home)

    def test_default_jog_deadband_and_zero_rotation_unchanged(self):
        self.assertTrue(self.service.rotate_to_rz(-3.88)['ok'])
        self.assertTrue(self.service.rotate_to_rz(-3.9,force_delta=0)['ok'])
        self.assertEqual(self.commands,[])

    def test_small_height_settle_lifts_before_crossing(self):
        for height in (299.989,299.991):
            with self.subTest(height=height):
                start = dict(self.pose,Z=height,Rz=-3.901)
                stages = queued_station_stages(start,self.home,self.joints,self.cfg,self.env)
                self.assertEqual(stages[0]['kind'],'queue')
                self.assertEqual(stages[0]['points'][-1]['Z'],300)
                current = start
                for stage in stages:
                    if stage['kind']=='rotate':
                        current = dict(current,Rz=stage['rz'])
                    else:
                        validate_home_transit(current,stage['points'])
                        current = stage['points'][-1]

    def test_nonfinite_feedback_rejected(self):
        self.guard.rotate_to_rz.side_effect = None
        self.pose['Rz'] = float('nan')
        with self.assertRaises(TransferError):
            rotate_home_wrist(self.guard,-3.88)


if __name__ == '__main__':
    unittest.main()
