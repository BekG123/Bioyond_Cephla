"""Fixed two-speed lift checks with fake hardware and real IK validation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import staged_lift_trial as trial
from autonomy import TransferError


class Service:
    def __init__(self):
        self.pose = dict(X=312.575,Y=-66.2,Z=73.718,Rz=89.865)
        self.q = dict(J1=35.119,J2=40.7994,J3=59.33,J4=-10.2643)
        self.envelope = dict(X=[200,450],Y=[-250,380],Z=[70,400])
        self.envelope_enabled = True
        self.e1=3.7
        self.stops=[]
    def status(self):
        return dict(ok=True,connected=True,enabled=True,errors=[],pose_mm=dict(self.pose),
                    joints=dict(self.q),control_mode={'mode':'auto'},program_state={'state':'running'})
    def _preflight(self):return None
    def external_axes(self):return {'E1':self.e1}
    def pose_mm(self):return dict(self.pose)
    def joints(self):return dict(self.q)
    def program(self,action):
        self.stops.append(action)
        return dict(ok=True)


class Run:
    def stopped(self):return False
    def say(self,*args):pass
    def audit(self,*args,**kwargs):pass


class LiftTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out=patch.object(trial,'OUTPUT',Path(self.tmp.name)/'trial.json')
        out.start();self.addCleanup(out.stop)
        self.s=Service()
        self.cfg=json.loads((trial.ROOT/'operator_ui/robot_params.json').read_bytes())
        self.calls=[]
        self.fail_first=False
        test=self
        class Queue:
            def __init__(self,service):self.service=service
            def capability(self):return dict(available=True,max_speed_mm_s=137)
            def execute(self,run,start,joints,points,cfg,speed,progress,**kwargs):
                test.calls.append((points,speed))
                if test.fail_first:raise TransferError('Uncertain first lift')
                self.service.service.pose=dict(points[-1])
                progress('motion',100,100)
                return dict(ok=True)
        queue=patch.object(trial,'LuaTrajectory',Queue)
        queue.start();self.addCleanup(queue.stop)

    def test_two_vertical_stages_and_no_grip_command(self):
        plan=trial.review(self.s,self.cfg)
        self.assertEqual([s['speed'] for s in plan['stages']],[5,137])
        self.assertEqual([s['target']['Z'] for s in plan['stages']],[78.72,103.72])
        result=trial.execute(Run(),self.s,self.cfg,plan)
        self.assertTrue(result['ok'])
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.s.e1,3.7)
        self.assertFalse(result['grasp_verified'])
        with self.assertRaises(TransferError):trial.review(self.s,self.cfg)

    def test_first_failure_blocks_fast_stage_and_stops(self):
        plan=trial.review(self.s,self.cfg)
        self.fail_first=True
        with self.assertRaises(TransferError):trial.execute(Run(),self.s,self.cfg,plan)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.s.stops,['stop'])

    def test_changed_pose_or_grip_refused(self):
        self.s.pose['Z']+=5
        with self.assertRaises(TransferError):trial.review(self.s,self.cfg)
        self.s.pose['Z']-=5
        self.s.e1=3.8
        with self.assertRaises(TransferError):trial.review(self.s,self.cfg)
        self.assertEqual(self.calls,[])

    def test_workspace_excludes_final_height(self):
        self.s.envelope['Z'][1]=90
        with self.assertRaises(TransferError):trial.review(self.s,self.cfg)
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
