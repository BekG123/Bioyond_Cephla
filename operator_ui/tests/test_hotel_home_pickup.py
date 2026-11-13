import unittest
import tempfile
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock,patch
from autonomy import check_path
from plan_hotel_slot1 import build
import hotel_home_pickup as h
import hotel_slot2_pickup as slot2

class HomePickupTests(unittest.TestCase):
    def setUp(self):
        d=build();self.cfg=d['config'];self.calls=[]
        q=check_path(d['start'],h.ANCHOR,d['start_joints'],self.cfg,d['envelope']);q['J1']=h.ANCHOR['Z']-d['start']['Z']+d['start_joints']['J1']
        self.s=dict(connected=True,ok=True,errors=[],enabled=True,control_mode={'mode':'auto'},program_state={'state':'running'},pose_mm=deepcopy(h.ANCHOR),joints=q)
        self.axes={'E1':0.,'E2':1.936}
        self.svc=SimpleNamespace(status=lambda:deepcopy(self.s),_preflight=lambda:None,envelope_enabled=True,envelope=d['envelope'],move_gripper=self.open,program=lambda a: self.calls.append(('program',a)) or {'ok':True})
        self.run=SimpleNamespace(stopped=lambda:False,say=Mock(),audit=Mock())
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        read=lambda svc:dict(moving=False,error=False,emergency=False,drag=False,manual=False,external_axes=deepcopy(self.axes))
        for p in (patch.object(h,'native',read),patch.object(slot2,'native',read),patch.object(h,'OUTPUT',Path(self.tmp.name)),patch.object(h,'verify',self.restore)):
            p.start();self.addCleanup(p.stop)
        self.gripper=SimpleNamespace(_configuration=lambda receipt:({},'test_digest'),execute=self.grip)
    def restore(self,*args,**kw):self.axes['E2']=1.77;self.calls.append(('holder',1.77));return [1.77]*3
    def open(self,target,speed):self.axes['E1']=target;self.calls.append(('open',target));return {'ok':True}
    def grip(self,run,receipt):
        self.assertEqual(receipt['descent_result']['plate_profile_id'],'48_well_projected_20261026')
        self.axes['E1']=3.9;self.calls.append(('grip',3.9));return {'ok':True}
    def queue(self,run,start,joints,points,cfg,speed,monitor,**kw):
        phase=kw['hotel_route'];self.calls.append(('queue',phase));monitor()
        self.s['pose_mm']=deepcopy(points[-1]);self.s['joints']=deepcopy(self.p['geometry']['routes'][phase]['expected']);monitor()
        return {'ok':True}
    def test_accepted_profile_pickup_no_hotel_travel(self):
        self.p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):
            result=h.execute(self.run,self.svc,self.cfg,self.p,self.gripper)
        self.assertEqual(self.calls,[('holder',1.77),('queue','home48_connect'),('open',28),('queue','home48_descend'),('grip',3.9),('queue','home48_lift')])
        self.assertAlmostEqual(result['pose_mm']['Z'],78.72,places=2)
    def test_route_profile_bound_and_speed_checked(self):
        p=h.preview(self.svc,self.cfg);owner=h.HomePickupService(self.svc,p);r=p['geometry']['routes']['home48_connect']
        h.prepare_for_service(owner,'home48_connect',p['start'],p['joints'],r['points'],self.cfg,p['geometry']['envelope'],r['speeds'])
        with self.assertRaises(Exception):h.prepare_for_service(owner,'home48_connect',p['start'],p['joints'],r['points'],self.cfg,p['geometry']['envelope'],[137,137])
        self.assertEqual(self.calls,[])
    def test_failed_connector_stops_before_open_or_grip(self):
        p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',return_value={'ok':False,'error':'collision'}):
            with self.assertRaisesRegex(Exception,'no retry'):h.execute(self.run,self.svc,self.cfg,p,self.gripper)
        self.assertEqual(self.calls,[('holder',1.77),('program','stop')])

if __name__=='__main__':unittest.main()
