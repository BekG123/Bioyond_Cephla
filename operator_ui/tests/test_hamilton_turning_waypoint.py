"""Revised geometry and serialized Lua queue, without real hardware."""
import json
import sys
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plan_hamilton_turning_waypoint import build,FOLDER
from trajectory_queue import LuaTrajectory,checksum
from test_transfer import FakeService
from test_trajectory_queue import Controller
from test_researcher_workflow import FakeRunner
from autonomy import TransferError

class TurningTests(unittest.TestCase):
    def test_dense_bidirectional_ik_and_taught_winding(self):
        plan=build()
        for route in plan['routes'].values():
            self.assertTrue(route['validation']['workspace_valid'])
            self.assertTrue(route['validation']['ik_and_joint_limits_valid'])
            self.assertLess(max(abs(v) for v in route['turning_pose_validation']['endpoint_joint_error'].values()),.02)
            self.assertGreater(len(route['validation']['dense_samples']),300)
    def test_exact_reverse_keeps_waypoint_and_endpoints(self):
        p=build();f=p['routes']['forward'];r=p['routes']['reverse']
        self.assertEqual([f['start']]+f['points'],list(reversed([r['start']]+r['points'])))
        self.assertEqual(f['points'][0],p['quantized_turning_pose'])
        self.assertFalse(p['execution_enabled']);self.assertFalse(p['collision_clearance_verified'])
        self.assertEqual(p['global_envelope']['Z']['min'],70)
    def test_real_lua_preserves_two_moves_speed_and_external_axes(self):
        p=build()
        package=Path(__file__).resolve().parents[2]/'controller/main_hostpoint_e2_holder_speed137_queue_220109.bin'
        with zipfile.ZipFile(package) as archive:source=archive.read('main/mod_Trajectory.lua').decode()
        for route in p['routes'].values():
            s=FakeService();s.cfg=p['config'];s.pose=route['start'].copy();s.q=route['start_joints'].copy()
            s.robot=Controller(s,source=source);executor=LuaTrajectory(s);token=123
            executor._job(1,token,dict(enumerate(route['payload']['header'])))
            executor._job(2,token,dict(enumerate(v for point in route['points'] for v in point.values())),0,2)
            executor._job(3,token,offset=checksum(route['points']))
            self.assertEqual(s.robot.calls,[])
            executor._job(4,token)
            self.assertEqual(len(s.robot.calls),2);self.assertEqual(s.robot.barriers,1)
            for call,point in zip(s.robot.calls,route['points']):
                self.assertEqual(call[1:3],(137,-1))
                self.assertEqual(call[0][6:9],(3.4,-2,0))
                for index,key in ((0,'X'),(1,'Y'),(2,'Z'),(5,'Rz')):self.assertAlmostEqual(call[0][index],point[key],places=3)
    def test_failure_evidence_kept(self):
        old=json.loads((FOLDER/'hamilton_short_side_reverse_trial01.json').read_bytes())
        self.assertEqual(old['status'],'failed_or_uncertain')
        self.assertIn('collision',old['error'])
    def test_live_executor_profile_checks_and_runs_both_directions(self):
        p=build()
        for direction,route in p['routes'].items():
            s=FakeService();s.cfg=p['config'];s.pose=route['start'].copy();s.q=route['start_joints'].copy()
            s.envelope={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
            s.robot=Controller(s);s._locked=lambda fn:fn()
            run=FakeRunner();run.cancelled=False
            result=LuaTrajectory(s).execute(run,s.pose,s.q,route['points'],s.cfg,137,lambda *a:None,reviewed=True,hamilton_short_side='turning01_'+direction)
            self.assertTrue(result['ok']);self.assertEqual(len(s.robot.calls),2)
            self.assertEqual(s.robot.barriers,1)
    def test_live_executor_cannot_skip_clearance_waypoint(self):
        p=build();route=p['routes']['forward'];s=FakeService();s.cfg=p['config'];s.pose=route['start'].copy();s.q=route['start_joints'].copy()
        s.envelope={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
        s.robot=Controller(s);run=FakeRunner();run.cancelled=False
        with self.assertRaises(TransferError):
            LuaTrajectory(s).execute(run,s.pose,s.q,route['points'][1:],s.cfg,137,lambda *a:None,reviewed=True,hamilton_short_side='turning01_forward')
        self.assertEqual(s.robot.jobs,[])

if __name__=='__main__':unittest.main()
