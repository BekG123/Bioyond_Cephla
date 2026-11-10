"""No-hardware checks for pickup-to-Hamilton revision 02."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from short_side_direct_transfer import reference,build
from trajectory_queue import LuaTrajectory
from autonomy import TransferError
from test_transfer import FakeService
from test_trajectory_queue import Controller
from test_researcher_workflow import FakeRunner

class DirectTransferTests(unittest.TestCase):
    def setup_route(self,direction):
        p,_,_=reference();route=p['routes'][direction]
        s=FakeService();s.cfg=p['config'];s.pose=route['start'].copy();s.q=route['start_joints'].copy()
        s.envelope={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
        s.robot=Controller(s);s._locked=lambda fn:fn()
        run=FakeRunner();run.cancelled=False
        self.s,self.run,self.points,self.direction=s,run,copy.deepcopy(route['points']),direction
    def execute(self,speed=137):
        return LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,self.points,self.s.cfg,speed,lambda *a:None,reviewed=True,hamilton_short_side='pickup_turning02_'+self.direction)
    def test_dense_ik_both_directions_and_taught_branch(self):
        p=build()
        self.assertTrue(p['taught_joint_branch_validation']['workspace_valid'])
        for route in p['routes'].values():
            self.assertTrue(route['validation']['workspace_valid'])
            self.assertTrue(route['validation']['ik_and_joint_limits_valid'])
            self.assertGreater(len(route['validation']['dense_samples']),700)
    def test_finish_turn_before_fixed_yaw_entry_and_reverse(self):
        p,parent,grip=reference();f=p['routes']['forward'];r=p['routes']['reverse']
        self.assertEqual(f['start'],grip['proof_lift_endpoint'])
        self.assertEqual([f['start']]+f['points'],list(reversed([r['start']]+r['points'])))
        a,b,end=f['points']
        self.assertEqual([a[k] for k in ('X','Y','Z')],[b[k] for k in ('X','Y','Z')])
        self.assertEqual(b['Rz'],end['Rz'])
        self.assertFalse(p['home_between_pickup_and_hamilton'])
        self.assertNotIn(parent['home'],f['points'])
        self.assertEqual(p['global_envelope']['Z']['min'],70)
    def test_real_lua_one_queue_three_moves_preserves_axes(self):
        for direction in ('forward','reverse'):
            self.setup_route(direction);self.assertTrue(self.execute()['ok'])
            self.assertEqual(self.s.robot.barriers,1);self.assertEqual(len(self.s.robot.calls),3)
            for call in self.s.robot.calls:
                self.assertEqual(call[1:3],(137,-1));self.assertEqual(call[0][6:9],(3.4,-2,0))
            self.assertEqual(self.s.grips,[])
    def test_home_start_skipped_turn_and_overspeed_refused(self):
        self.setup_route('forward');_,parent,_=reference();self.s.pose=parent['home']
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])
        self.setup_route('forward');self.points.pop(1)
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])
        self.setup_route('forward')
        with self.assertRaises(TransferError):self.execute(138)
        self.assertEqual(self.s.robot.jobs,[])
    def test_runner_has_no_loaded_home_call(self):
        source=(Path(__file__).resolve().parents[1]/'run_short_side_pickup_to_hamilton.py').read_text()
        self.assertNotIn('move_home',source);self.assertNotIn('loaded_home',source)
        self.assertIn("checked((24.93,25.07),high,holder_required=False)",source)
        self.assertIn("phase='hamilton'",source)

if __name__=='__main__':unittest.main()
