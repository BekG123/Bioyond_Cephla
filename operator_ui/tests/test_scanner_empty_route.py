import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_trajectory_queue import Controller, FakeService, FakeRunner, PARAMS
from autonomy import TransferError
from trajectory_queue import LuaTrajectory
import scanner_empty_route as scanner


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.s=FakeService()
        self.s.pose=dict(scanner.START)
        self.s.q=dict(J1=209.4212,J2=84.87684236708007,J3=52.05594907317273,J4=-140.8128286807219)
        self.s.envelope=dict(scanner.ORIGINAL)
        self.s.robot=Controller(self.s)
        self.s._locked=lambda fn:fn()
        self.s.status=lambda:dict(ok=True,connected=True,errors=[],enabled=True,
            control_mode={'mode':'auto'},program_state={'state':'running'},pose_mm=self.s.pose.copy(),
            joints=self.s.q.copy(),external_axes={'E1':4.355})
        def envelope(x0,x1,y0,y1,z0,z1):
            self.s.envelope=dict(X=(x0,x1),Y=(y0,y1),Z=(z0,z1))
            return {'ok':True}
        self.s.set_envelope=envelope
        self.run=FakeRunner();self.run.cancelled=False

    def test_actual_lua_executes137_and_restores_workspace(self):
        approved=scanner.plan(self.s,PARAMS)
        with tempfile.TemporaryDirectory() as folder, patch.object(scanner,'ROOT',Path(folder)):
            result=scanner.execute(self.run,self.s,PARAMS,approved)
            self.assertTrue(result['ok'])
            record=json.loads(Path(result['record']).read_text())
            self.assertEqual(record['status'],'completed')
            self.assertTrue(record['envelope_restoration']['ok'])
        self.assertEqual(len(self.s.robot.calls),1)
        self.assertEqual(self.s.robot.barriers,1)
        self.assertEqual(record['result']['validation_waypoints'],7)
        self.assertTrue(record['result']['continuous_collinear'])
        self.assertEqual([j[4] for j in self.s.robot.jobs],[6,1,2,3,4])
        self.assertTrue(all(c[1]==137 for c in self.s.robot.calls))
        self.assertEqual(self.s.grips,[])
        self.assertEqual(self.s.envelope,scanner.ORIGINAL)

    def test_reverse_then_forward_each_one_move_one_queue(self):
        self.s.q=scanner.continuous_endpoint(self.s.pose,scanner.points(),self.s.q,PARAMS,scanner.TRIAL)[1]
        self.s.pose=dict(scanner.TARGET)
        for direction,endpoint in [('to_idle',scanner.START),('to_scanner',scanner.TARGET)]:
            approved=scanner.plan(self.s,PARAMS)
            self.assertEqual(approved['direction'],direction)
            with tempfile.TemporaryDirectory() as folder, patch.object(scanner,'ROOT',Path(folder)):
                result=scanner.execute(self.run,self.s,PARAMS,approved)
            for k in scanner.KEYS:self.assertAlmostEqual(result['pose_mm'][k],endpoint[k],places=4)
        self.assertEqual(len(self.s.robot.calls),2)
        self.assertEqual(self.s.robot.barriers,2)
        self.assertEqual(self.s.grips,[])

    def test_stop_during_continuous_move_never_dispatches_again(self):
        self.s.envelope=dict(scanner.TRIAL)
        self.s.robot.block_motion=True
        self.run.stopped=lambda:self.s.robot.started.is_set()
        def stop(action):
            self.assertEqual(action,'stop')
            self.s.robot.program_state='stopped'
            self.s.robot.released.set()
            return dict(ok=True)
        self.s.program=stop
        with self.assertRaises(TransferError):
            LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,scanner.points(),PARAMS,137,
                lambda *a:None,reviewed=True,scanner_empty='continuous')
        self.assertTrue(self.s.robot.released.is_set())
        self.assertEqual(len(self.s.robot.calls),1)
        self.assertEqual(sum(j[4]==4 for j in self.s.robot.jobs),1)

    def test_continuous_route_edit_rejected_before_controller_write(self):
        self.s.envelope=dict(scanner.TRIAL)
        edited=scanner.points();edited[3]['Y']+=.1
        with self.assertRaises(TransferError):
            LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,edited,PARAMS,137,
                lambda *a:None,reviewed=True,scanner_empty='continuous')
        self.assertEqual(self.s.robot.jobs,[])

    def test_edited_target_and_changed_start_refused(self):
        approved=scanner.plan(self.s,PARAMS)
        approved['points'][-1]['X']+=1
        with self.assertRaises(TransferError):scanner.execute(self.run,self.s,PARAMS,approved)
        self.assertEqual(self.s.robot.jobs,[])
        self.s.pose['X']+=1
        with self.assertRaises(TransferError):scanner.plan(self.s,PARAMS)

    def test_wrong_speed_and_profile_rejected_before_upload(self):
        self.s.envelope=dict(scanner.TRIAL)
        executor=LuaTrajectory(self.s)
        for speed,options in ((138,{}),(137,{'home_speed137':True}),(40,{})):
            with self.assertRaises(TransferError):
                executor.execute(self.run,self.s.pose,self.s.q,scanner.points(),PARAMS,speed,
                                 lambda *a:None,reviewed=True,scanner_empty=True,**options)
        self.assertEqual(self.s.robot.jobs,[])

    def test_queue_failure_restores_envelope_without_retry(self):
        approved=scanner.plan(self.s,PARAMS)
        with tempfile.TemporaryDirectory() as folder, patch.object(scanner,'ROOT',Path(folder)), \
             patch.object(LuaTrajectory,'execute',side_effect=TransferError('unknown motion')) as execute:
            with self.assertRaises(TransferError):scanner.execute(self.run,self.s,PARAMS,approved)
            self.assertEqual(execute.call_count,1)
            record=json.loads(next(Path(folder).rglob('position_*.json')).read_text())
            self.assertEqual(record['status'],'stopped_or_uncertain')
        self.assertEqual(self.s.envelope,scanner.ORIGINAL)


if __name__=='__main__':unittest.main()
