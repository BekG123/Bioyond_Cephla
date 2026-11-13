import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import hotel_slot3_handling as h
import hotel_slot2_pickup as state_module
from hotel_slot_trial import reference


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.g=h.geometry();base,_=reference();self.cfg=self.g['cfg'];self.calls=[]
        self.axes={'E1':7.,'E2':1.77}
        self.s=dict(connected=True,ok=True,errors=[],enabled=True,control_mode={'mode':'auto'},program_state={'state':'running'},
                    pose_mm=deepcopy(self.g['home']),joints=deepcopy(base['start_joints']))
        self.svc=SimpleNamespace(status=lambda:deepcopy(self.s),_preflight=lambda:None,envelope_enabled=True,
                    envelope=self.g['envelope'],move_gripper=self.jaw,program=lambda action:self.calls.append(('program',action)) or {'ok':True})
        self.run=SimpleNamespace(stopped=lambda:False,say=Mock(),audit=Mock())
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        read=lambda svc:dict(moving=False,error=False,emergency=False,drag=False,manual=False,external_axes=deepcopy(self.axes))
        for p in (patch.object(state_module,'native',read),patch.object(h,'OUTPUT',Path(self.tmp.name))):
            p.start();self.addCleanup(p.stop)
    def jaw(self,target,speed):
        self.axes['E1']=target;self.calls.append(('jaw',target,speed));return {'ok':True}
    def queue(self,run,start,joints,points,cfg,speed,monitor,**kw):
        name=kw['hotel_route'].removeprefix(h.PREFIX);self.calls.append(('queue',name));monitor()
        self.s['pose_mm']=deepcopy(points[-1]);self.s['joints']=deepcopy(self.g['routes'][name]['expected']);monitor()
        return {'ok':True}
    def test_release_precedes_horizontal_empty_return(self):
        r=self.g['routes']['empty_return']
        self.s['pose_mm']=deepcopy(r['start'])
        self.s['joints']=deepcopy(self.g['approach_geometry']['route']['expected'])
        self.axes['E1']=3.9
        p=h.preview(self.svc,self.cfg,'release_return')
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):
            result=h.execute(self.run,self.svc,self.cfg,p)
        self.assertEqual(self.calls,[('jaw',7,5),('queue','empty_return')])
        self.assertEqual(result['plate_location'],'slot3')
        self.assertEqual(r['points'][0]['Z'],r['start']['Z'])

    def test_complete_order_and_release_only_after_seating(self):
        p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):result=h.execute(self.run,self.svc,self.cfg,p)
        self.assertTrue(result['ok'])
        self.assertEqual(self.calls,[('queue','approach'),('jaw',4.9,10),('jaw',3.9,5),('queue','lift'),
            ('queue','return'),('queue','seat'),('jaw',28,5),('queue','clear')])
    def test_failed_lift_stops_without_withdrawal_or_release(self):
        p=h.preview(self.svc,self.cfg)
        def execute(*args,**kw):
            if kw['hotel_route']==h.PREFIX+'lift':return {'ok':False,'error':'uncertain'}
            return self.queue(*args,**kw)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=execute):
            with self.assertRaisesRegex(Exception,'no retry'):h.execute(self.run,self.svc,self.cfg,p)
        self.assertNotIn(('queue','return'),self.calls);self.assertNotIn(('jaw',28,5),self.calls)
        self.assertEqual(self.calls[-1],('program','stop'))
    def test_horizontal_after_five_mm_lift_and_slow_contact_phases(self):
        r=self.g['routes'];end=r['approach']['points'][-1];lift=r['lift']['points'][0];exit=r['return']['points'][0]
        self.assertEqual(lift['Z']-end['Z'],5)
        for key in ('Y','Z','Rz'):self.assertEqual(exit[key],lift[key])
        self.assertEqual(exit['X'],154.409)
        self.assertEqual(r['lift']['speeds'],[5]);self.assertEqual(r['approach']['speeds'][-2:],[137,20])
        self.assertAlmostEqual(end['X'],293.720)
        self.assertEqual(r['return']['speeds'],[20,137,137,137,137,137])
    def test_route_speed_and_owner_bound(self):
        p=h.preview(self.svc,self.cfg);owner=h.RetrievalService(self.svc,p);r=self.g['routes']['approach']
        h.prepare_for_service(owner,h.PREFIX+'approach',p['start'],p['joints'],r['points'],self.cfg,self.g['envelope'],r['speeds'])
        with self.assertRaises(Exception):h.prepare_for_service(owner,h.PREFIX+'approach',p['start'],p['joints'],r['points'],self.cfg,self.g['envelope'],[137]*6)
        with self.assertRaises(Exception):h.prepare_for_service(self.svc,h.PREFIX+'approach',p['start'],p['joints'],r['points'],self.cfg,self.g['envelope'],r['speeds'])
        self.assertEqual(self.calls,[])
    def test_seating_uses_existing_half_degree_motion_tolerance(self):
        p=h.preview(self.svc,self.cfg)
        def execute(*args,**kw):
            if kw['hotel_route']==h.PREFIX+'seat':self.axes['E2']=1.7300979091
            return self.queue(*args,**kw)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=execute):result=h.execute(self.run,self.svc,self.cfg,p)
        self.assertTrue(result['ok']);self.assertIn(('jaw',28,5),self.calls)

    def test_seating_stops_on_angle_beyond_existing_motion_tolerance(self):
        p=h.preview(self.svc,self.cfg)
        def execute(*args,**kw):
            if kw['hotel_route']==h.PREFIX+'seat':self.axes['E2']=1.20
            return self.queue(*args,**kw)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=execute):
            with self.assertRaisesRegex(Exception,'during seating'):h.execute(self.run,self.svc,self.cfg,p)
        self.assertNotIn(('jaw',28,5),self.calls)

    def test_home_holder_gate_prevents_seating_and_release(self):
        p=h.preview(self.svc,self.cfg)
        def execute(*args,**kw):
            v=self.queue(*args,**kw)
            if kw['hotel_route']==h.PREFIX+'return':self.axes['E2']=2.0
            return v
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=execute):
            with self.assertRaisesRegex(Exception,'holder angle'):h.execute(self.run,self.svc,self.cfg,p)
        self.assertNotIn(('queue','seat'),self.calls);self.assertNotIn(('jaw',28,5),self.calls)


if __name__=='__main__':unittest.main()
