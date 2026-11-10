"""Pinned route execution and refusal tests using real Lua, fake hardware."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_transfer import FakeService
from test_trajectory_queue import Controller
from test_researcher_workflow import FakeRunner
from trajectory_queue import LuaTrajectory
from hamilton_short_side_trial import reference,validate_route
from autonomy import TransferError

class RuntimeTests(unittest.TestCase):
    def setup_route(self,direction):
        p,parent=reference();s=FakeService();s.cfg=p['config']
        s.envelope={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
        s.pose=p['routes'][direction]['start'].copy()
        s.q=parent['home_joints' if direction=='forward' else 'measured_endpoint_joints'].copy()
        s.robot=Controller(s);s._locked=lambda fn:fn()
        def stop(action):
            self.assertEqual(action,'stop');s.robot.program_state='stopped';s.robot.released.set();return dict(ok=True)
        s.program=stop
        run=FakeRunner();run.cancelled=False
        self.s,self.run,self.points,self.direction=s,run,p['routes'][direction]['points'],direction
    def execute(self,**kwargs):
        return LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,self.points,self.s.cfg,kwargs.pop('speed',137),lambda *a:None,reviewed=True,hamilton_short_side=self.direction,**kwargs)
    def test_both_directions_one_motion(self):
        for direction in ('reverse','forward'):
            self.setup_route(direction);self.assertTrue(self.execute()['ok'])
            self.assertEqual(len(self.s.robot.calls),1);self.assertEqual(self.s.robot.barriers,1)
            self.assertEqual(self.s.robot.calls[0][1:3],(137,-1));self.assertEqual(self.s.grips,[])
    def test_changed_endpoint_or_winding_rejected_before_upload(self):
        self.setup_route('forward');self.points=copy.deepcopy(self.points);self.points[0]['X']+=.01
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])
        self.setup_route('reverse');self.s.q['J4']+=360
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])
    def test_profile_conflicts_and_speed_rejected(self):
        for flags in ({'speed':138},{'grouped':True},{'home_transit':True},{'short_side_alignment':'corrected02'}):
            self.setup_route('forward')
            with self.assertRaises(TransferError):self.execute(**flags)
            self.assertEqual(self.s.robot.jobs,[])
    def test_actual_unloaded_start_rechecked(self):
        self.setup_route('reverse')
        self.s.pose=dict(X=373.833,Y=-184.216,Z=52.026,Rz=-93.299)
        self.s.q=dict(J1=13.4266882714,J2=2.84262381399,J3=101.0672368354,J4=-197.2085623282)
        self.assertTrue(self.execute()['ok'])
    def test_position_below_station_floor_rejected(self):
        self.setup_route('reverse');self.s.pose['Z']-=.02
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])
    def test_monitor_failure_stops_without_retry(self):
        self.setup_route('reverse')
        def fail(*args):raise TransferError('Unhealthy feedback')
        with self.assertRaises(TransferError):
            LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,self.points,self.s.cfg,137,fail,reviewed=True,hamilton_short_side='reverse')
        self.assertEqual(self.s.robot.program_state,'stopped');self.assertEqual(self.s.robot.calls,[])

if __name__=='__main__':unittest.main()
