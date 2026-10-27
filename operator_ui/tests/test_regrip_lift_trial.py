"""Regrip order and failure containment, fake hardware with real path checks."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import regrip_lift_trial as trial
from test_staged_lift_trial import Service, Run
from autonomy import TransferError


class RegripTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        active=patch.object(trial,'OUTPUT',Path(self.tmp.name)/'trial.json')
        active.start();self.addCleanup(active.stop)
        active=patch.object(trial,'OUTPUT_7',Path(self.tmp.name)/'trial7.json')
        active.start();self.addCleanup(active.stop)
        self.s=Service()
        self.s.pose=dict(X=312.58,Y=-66.2,Z=103.72,Rz=89.87)
        self.s.q=dict(J1=65.12135,J2=40.7991,J3=59.33145,J4=-10.26067)
        parent=json.loads(trial.PARENT.read_bytes())
        self.cfg=parent['plan']['cfg']
        self.events=[]
        self.fail_jaw=False
        self.fail_return=False
        self.fail_report=False
        test=self
        def jaw(target,speed):
            test.events.append(('jaw',target,speed))
            if test.fail_jaw:return dict(ok=False)
            test.s.e1=target
            return dict(ok=True)
        self.s.move_gripper=jaw
        self.s.torque_report=lambda:dict(ok=not self.fail_report,telemetry_live=True,
                                         e1_position=self.s.e1,e1_torque=86)
        class Queue:
            def __init__(self,service):self.service=service
            def capability(self):return dict(available=True,max_speed_mm_s=137)
            def execute(self,run,start,joints,points,cfg,speed,progress,**kwargs):
                test.events.append(('arm',points[-1]['Z'],speed))
                if test.fail_return:raise TransferError('Return uncertain')
                self.service.service.pose=dict(points[-1])
                return dict(ok=True)
        active=patch.object(trial,'LuaTrajectory',Queue)
        active.start();self.addCleanup(active.stop)

    def test_order_support_then_open_reclose_and_lift(self):
        approved=trial.review(self.s,self.cfg)
        result=trial.execute(Run(),self.s,self.cfg,approved)
        self.assertTrue(result['ok'])
        self.assertEqual(self.events[0],('arm',73.72,5))
        self.assertEqual(self.events[1],('jaw',5,5))
        self.assertEqual(self.events[-3:],[('jaw',3.7,5),('arm',78.72,5),('arm',103.72,137)])
        self.assertFalse(result['grasp_verified'])
        with self.assertRaises(TransferError):trial.review(self.s,self.cfg)

    def test_failed_return_never_opens(self):
        approved=trial.review(self.s,self.cfg)
        self.fail_return=True
        with self.assertRaises(TransferError):trial.execute(Run(),self.s,self.cfg,approved)
        self.assertEqual(len(self.events),1)
        self.assertEqual(self.s.stops,['stop'])

    def test_uncertain_jaw_never_closes_or_lifts(self):
        approved=trial.review(self.s,self.cfg)
        self.fail_jaw=True
        with self.assertRaises(TransferError):trial.execute(Run(),self.s,self.cfg,approved)
        self.assertEqual(self.events,[('arm',73.72,5),('jaw',5,5)])
        self.assertEqual(self.s.stops,['stop'])

    def test_missing_torque_stops_before_closure(self):
        approved=trial.review(self.s,self.cfg)
        self.fail_report=True
        with self.assertRaises(TransferError):trial.execute(Run(),self.s,self.cfg,approved)
        self.assertEqual(len(self.events),2)

    def test_changed_start_refused(self):
        self.s.pose['Z']+=1
        with self.assertRaises(TransferError):trial.review(self.s,self.cfg)
        self.assertEqual(self.events,[])

    def test_open7_changes_only_opening_and_extra_closing_steps(self):
        five=trial.review(self.s,self.cfg)
        seven=trial.review(self.s,self.cfg,7)
        self.assertEqual(five['legs'],seven['legs'])
        self.assertEqual(seven['closing_targets'],[6,5]+five['closing_targets'])
        result=trial.execute(Run(),self.s,self.cfg,seven)
        self.assertTrue(result['ok'])
        self.assertEqual(self.events[:4],[('arm',73.72,5),('jaw',7,5),('jaw',6,5),('jaw',5,5)])
        self.assertEqual(self.events[-3:],[('jaw',3.7,5),('arm',78.72,5),('arm',103.72,137)])
        self.assertTrue(trial.OUTPUT_7.exists())
        self.assertFalse(trial.OUTPUT.exists())
        with self.assertRaises(TransferError):trial.review(self.s,self.cfg,7)

    def test_arbitrary_opening_refused(self):
        for opening in (True,'7',6,8,float('nan')):
            with self.assertRaises(TransferError):trial.review(self.s,self.cfg,opening)
        self.assertEqual(self.events,[])


if __name__=='__main__':unittest.main()
