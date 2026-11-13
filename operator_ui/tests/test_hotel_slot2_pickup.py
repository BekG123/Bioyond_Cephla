import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import hotel_slot2_pickup as h

class Slot2Tests(unittest.TestCase):
    def setUp(self):
        self.g=h.geometry();self.cfg=self.g['cfg'];self.calls=[]
        from plan_hotel_slot1 import build
        base=build();self.s=dict(connected=True,ok=True,errors=[],enabled=True,control_mode={'mode':'auto'},
            program_state={'state':'running'},pose_mm=deepcopy(base['start']),joints=deepcopy(base['start_joints']))
        self.axes={'E1':.02,'E2':1.925}
        self.svc=SimpleNamespace(status=lambda:deepcopy(self.s),_preflight=lambda:None,envelope_enabled=True,
            envelope=self.g['envelope'],move_gripper=self.gripper,program=self.program)
        self.run=SimpleNamespace(stopped=lambda:False,say=Mock())
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for p in (patch.object(h,'OUTPUT',Path(self.tmp.name)),patch.object(h,'native',lambda svc:dict(
                moving=False,error=False,emergency=False,drag=False,manual=False,external_axes=deepcopy(self.axes))),
                patch.object(h.time,'sleep',lambda n:None)):
            p.start();self.addCleanup(p.stop)
    def gripper(self,target,speed):
        self.calls.append(('jaw',target,speed));self.axes['E1']=target;return {'ok':True}
    def program(self,action):self.calls.append(('program',action));return {'ok':True}
    def queue(self,run,start,joints,points,cfg,speed,monitor,**kw):
        phase=kw['hotel_route'];self.calls.append(('queue',phase))
        monitor();self.s['pose_mm']=deepcopy(points[-1]);self.s['joints']=deepcopy(self.g['routes'][phase]['expected']);monitor()
        return {'ok':True}
    def test_geometry_clearance_and_exact_speed_profiles(self):
        r=self.g['routes'];self.assertAlmostEqual(r['slot2_approach']['points'][-1]['Z'],301.659)
        self.assertAlmostEqual(r['slot2_lift']['points'][-1]['Z'],306.659)
        self.assertEqual(r['slot2_return']['points'][0]['Z'],r['slot2_lift']['points'][0]['Z'])
        p=h.preview(self.svc,self.cfg);owner=h.Slot2Service(self.svc,p);a=r['slot2_approach']
        out,q=h.prepare_for_service(owner,'slot2_approach',self.s['pose_mm'],self.s['joints'],a['points'],self.cfg,self.g['envelope'],a['speeds'])
        with self.assertRaises(Exception):h.prepare_for_service(owner,'slot2_approach',self.s['pose_mm'],self.s['joints'],a['points'],self.cfg,self.g['envelope'],[137]*3)
        with self.assertRaises(Exception):h.prepare_for_service(self.svc,'slot2_approach',self.s['pose_mm'],self.s['joints'],a['points'],self.cfg,self.g['envelope'],a['speeds'])
        self.assertEqual(self.calls,[])
    def test_pickup_stops_at_proof_then_bound_return(self):
        p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):
            result=h.execute(self.run,self.svc,self.cfg,p)
        self.assertEqual(self.calls,[('jaw',28,5),('queue','slot2_approach'),('jaw',4.9,10),('jaw',3.9,5),('queue','slot2_lift')])
        self.assertEqual(result['status'],'proof_lift_completed_retention_pending')
        ret=h.preview(self.svc,self.cfg,'return',result['record'])
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):
            returned=h.execute(self.run,self.svc,self.cfg,ret)
        self.assertEqual(returned['status'],'returned_HOME_held_pending_assessment')
        self.assertEqual(self.axes['E1'],3.9)
        with self.assertRaises(Exception):h.preview(self.svc,self.cfg,'return',result['record'])
    def test_queue_fault_stops_before_grip_and_lift(self):
        p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',return_value={'ok':False,'error':'fault'}):
            with self.assertRaisesRegex(Exception,'no retry'):h.execute(self.run,self.svc,self.cfg,p)
        self.assertEqual(self.calls,[('jaw',28,5),('program','stop')])
    def test_unhealthy_or_wrong_jaws_no_commands(self):
        self.s['program_state']['state']='stopped'
        with self.assertRaises(Exception):h.preview(self.svc,self.cfg)
        self.s['program_state']['state']='running';self.axes['E1']=3.9
        with self.assertRaises(Exception):h.preview(self.svc,self.cfg)
        self.assertEqual(self.calls,[])
    def test_grip_mismatch_stops_before_lift(self):
        p=h.preview(self.svc,self.cfg);original=self.svc.move_gripper
        def slip(target,speed):
            r=original(target,speed)
            if target==3.9:self.axes['E1']=4.2
            return r
        self.svc.move_gripper=slip
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):
            with self.assertRaisesRegex(Exception,'Jaw feedback'):h.execute(self.run,self.svc,self.cfg,p)
        self.assertNotIn(('queue','slot2_lift'),self.calls);self.assertEqual(self.calls[-1],('program','stop'))

if __name__=='__main__':unittest.main()
