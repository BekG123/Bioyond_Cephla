"""Exercise saved candidate payload with real Lua and fake vendor hardware."""
import json
from pathlib import Path
import sys
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_transfer import FakeService
from test_trajectory_queue import Controller
from trajectory_queue import LuaTrajectory,checksum
from short_side_alignment_trial import FOLDER

class HamiltonPlanTests(unittest.TestCase):
    def setUp(self):self.plan=json.loads((FOLDER/'hamilton_short_side_ik_plan.json').read_bytes())
    def replay_fake(self,reverse):
        p=self.plan;s=FakeService();s.cfg=p['config']
        if reverse:
            s.pose=p['reverse']['start'].copy();s.q=p['measured_endpoint_joints'].copy();points=p['reverse']['points']
        else:
            s.pose=p['home'].copy();s.q=p['home_joints'].copy();points=p['candidates']['direct']['points']
        package=Path(__file__).resolve().parents[2]/'controller/main_hostpoint_e2_holder_speed137_queue_220109.bin'
        with zipfile.ZipFile(package) as archive:source=archive.read('main/mod_Trajectory.lua').decode()
        s.robot=Controller(s,source=source);executor=LuaTrajectory(s);token=123
        header=[1,137,-1]+[s.pose[k] for k in ('X','Y','Z','Rz')]+[s.q[k] for k in ('J1','J2','J3','J4')]
        executor._job(1,token,dict(enumerate(header)))
        executor._job(2,token,dict(enumerate(points[0][k] for k in ('X','Y','Z','Rz'))),0,1)
        executor._job(3,token,offset=checksum(points))
        executor._job(4,token)
        self.assertEqual(len(s.robot.calls),1);self.assertEqual(s.robot.barriers,1)
        self.assertEqual(s.robot.calls[0][1:3],(137,-1))
        self.assertEqual(s.robot.calls[0][0][6:9],(3.4,-2,0))
        for k,v in points[0].items():self.assertAlmostEqual(s.pose[k],v,places=3)
    def test_forward_one_motion(self):self.replay_fake(False)
    def test_reverse_one_motion(self):self.replay_fake(True)
    def test_workspace_review_still_required(self):
        self.assertFalse(self.plan['execution_enabled'])
        self.assertFalse(self.plan['candidates']['direct']['validation']['workspace_valid'])
        self.assertFalse(self.plan['global_limits_changed'])
        self.assertGreater(len(self.plan['blockers']),0)

    def test_station_floor_scope_keeps_calibration_limits(self):
        p=json.loads((FOLDER/'hamilton_short_side_station_plan.json').read_bytes())
        self.assertEqual(p['global_envelope']['Z']['min'],70)
        self.assertEqual(p['station_envelope']['Z'][0],p['endpoint']['Z'])
        self.assertFalse(p['global_limits_changed'])
        self.assertFalse(p['execution_enabled'])
        for direction in ('forward','reverse'):
            self.assertTrue(p['routes'][direction]['validation']['workspace_valid'])
            self.assertTrue(p['routes'][direction]['validation']['ik_and_joint_limits_valid'])
        self.assertEqual(p['routes']['forward']['points'],self.plan['candidates']['direct']['points'])

if __name__=='__main__':unittest.main()
