import json
import unittest
import tempfile
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock,patch
from autonomy import check_path
from plan_hotel_slot1 import build
import hotel_slot1_delivery as h
import hotel_slot2_pickup as slot2

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        d=build();self.cfg=d['config'];self.calls=[]
        q=deepcopy(d['start_joints'])
        self.s=dict(connected=True,ok=True,errors=[],enabled=True,control_mode={'mode':'auto'},program_state={'state':'running'},pose_mm=deepcopy(d['start']),joints=q)
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
        self.s['pose_mm']=deepcopy(points[-1]);self.s['joints']=deepcopy(self.p['geometry']['routes'][phase.removeprefix(h.PREFIX)]['expected']);monitor()
        return {'ok':True}
    def test_pickup_delivery_release_then_horizontal_return(self):
        self.p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):
            result=h.execute(self.run,self.svc,self.cfg,self.p,self.gripper)
        self.assertEqual(self.calls,[('holder',1.77),('queue',h.PREFIX+'connect'),('open',28),('queue',h.PREFIX+'descend'),('grip',3.9),('queue',h.PREFIX+'proof'),('queue',h.PREFIX+'deliver'),('open',7),('queue',h.PREFIX+'return')])
        self.assertAlmostEqual(result['pose_mm']['Z'],105.72,places=2)

    def test_teaching_pickup_stops_after_proof_without_rack_travel_or_release(self):
        self.p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):
            result=h.execute(self.run,self.svc,self.cfg,self.p,self.gripper,pickup_only=True)
        self.assertEqual(self.calls,[('holder',1.77),('queue',h.PREFIX+'connect'),('open',28),('queue',h.PREFIX+'descend'),('grip',3.9),('queue',h.PREFIX+'proof')])
        self.assertFalse(result['rack_motion_started'])
        self.assertEqual(self.axes['E1'],3.9)
        self.assertAlmostEqual(result['pose_mm']['Z'],78.72)
    def test_route_profile_bound_and_speed_checked(self):
        p=h.preview(self.svc,self.cfg);owner=h.DeliveryService(self.svc,p);r=p['geometry']['routes']['connect']
        h.prepare_for_service(owner,h.PREFIX+'connect',p['start'],p['joints'],r['points'],self.cfg,p['geometry']['envelope'],r['speeds'])
        with self.assertRaises(Exception):h.prepare_for_service(owner,h.PREFIX+'connect',p['start'],p['joints'],r['points'],self.cfg,p['geometry']['envelope'],[137,137])
        self.assertEqual(self.calls,[])
    def test_failed_connector_stops_before_open_or_grip(self):
        p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',return_value={'ok':False,'error':'collision'}):
            with self.assertRaisesRegex(Exception,'no retry'):h.execute(self.run,self.svc,self.cfg,p,self.gripper)
        self.assertEqual(self.calls,[('holder',1.77),('program','stop')])

    def test_holder_angle_during_lift_does_not_stop_verified_grip(self):
        self.p=h.preview(self.svc,self.cfg)
        def queued(*args,**kw):
            if kw['hotel_route']==h.PREFIX+'proof':self.axes['E2']=1.70
            return self.queue(*args,**kw)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=queued):
            result=h.execute(self.run,self.svc,self.cfg,self.p,self.gripper)
        self.assertTrue(result['ok'])
        self.assertIn(('open',7),self.calls)

    def test_holder_angle_before_grip_remains_checked_and_recorded(self):
        self.p=h.preview(self.svc,self.cfg)
        def queued(*args,**kw):
            if kw['hotel_route']==h.PREFIX+'descend':self.axes['E2']=1.70
            return self.queue(*args,**kw)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=queued):
            with self.assertRaisesRegex(Exception,'E2=1.700000'):h.execute(self.run,self.svc,self.cfg,self.p,self.gripper)
        self.assertNotIn(('grip',3.9),self.calls)
        receipt=json.loads(next(Path(self.tmp.name).glob('*.json')).read_text())
        self.assertEqual(receipt['samples'][-1]['axes']['E2'],1.70)

    def test_failed_delivery_never_releases_or_returns(self):
        self.p=h.preview(self.svc,self.cfg)
        def queued(*args,**kw):
            if kw['hotel_route']==h.PREFIX+'deliver':return {'ok':False,'error':'arrival uncertain'}
            return self.queue(*args,**kw)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=queued):
            with self.assertRaisesRegex(Exception,'no retry'):h.execute(self.run,self.svc,self.cfg,self.p,self.gripper)
        self.assertNotIn(('open',7),self.calls)
        self.assertNotIn(('queue',h.PREFIX+'return'),self.calls)
        self.assertEqual(self.calls[-1],('program','stop'))

    def test_horizontal_entry_and_exit_lower_before_turn(self):
        g=h.geometry();forward=g['routes']['deliver']['points'];back=g['routes']['return']['points']
        for k in ('Y','Z','Rz'):self.assertEqual(forward[-2][k],forward[-1][k])
        self.assertEqual(back[0],forward[-2]);self.assertEqual(back[0]['X'],154.409)
        self.assertLess(back[1]['Z'],back[0]['Z'])
        self.assertEqual(back[1]['X'],back[0]['X'])
        self.assertEqual(back[1]['Y'],back[0]['Y'])
        self.assertTrue(all(p['Z']<=191.2 for p in back[1:]))
        start=g['routes']['deliver']['start'];q=g['routes']['proof']['expected']
        bad=deepcopy(forward);bad[-2]['X']=150
        with self.assertRaises(Exception):h.check_geometry(start,bad,q,g['cfg'],g['envelope'],True)

    def test_shorter_entry_preserves_height_and_reverse_endpoint(self):
        old=h.geometry(revision=2);new=h.geometry()
        previous=old['routes']['deliver']['points'][-1]
        endpoint=new['routes']['deliver']['points'][-1]
        self.assertAlmostEqual(previous['X']-endpoint['X'],6.35)
        for key in ('Y','Z','Rz'):self.assertEqual(previous[key],endpoint[key])
        self.assertEqual(new['routes']['return']['start'],endpoint)
        self.assertEqual(new['routes']['deliver']['speeds'],[137]*6+[50])
        self.assertEqual(new['routes']['proof']['speeds'],[5])
        self.assertEqual(new['routes']['return']['speeds'],[50,137,137,137,137,137])
        self.assertNotIn(str(h.CORRECTION),old['source_hashes'])
        self.assertIn(str(h.CORRECTION),new['source_hashes'])

    def test_fast_return_changes_only_speeds_and_binds_revision(self):
        old=h.geometry(revision=3);new=h.geometry(revision=4)
        for name in old['routes']:
            self.assertEqual(old['routes'][name]['points'],new['routes'][name]['points'])
            self.assertEqual(old['routes'][name]['expected'],new['routes'][name]['expected'])
            if name!='return':self.assertEqual(old['routes'][name],new['routes'][name])
        self.assertEqual(old['routes']['return']['speeds'],[5]*6)
        self.assertEqual(new['routes']['return']['speeds'],[5]+[137]*5)
        self.assertIn(str(h.RETURN_CORRECTION),new['source_hashes'])

    def test_horizontal_twenty_preserves_other_speeds_and_geometry(self):
        old=h.geometry(revision=4);new=h.geometry(revision=5)
        for name in old['routes']:
            self.assertEqual(old['routes'][name]['points'],new['routes'][name]['points'])
            self.assertEqual(old['routes'][name]['expected'],new['routes'][name]['expected'])
            if name not in ('deliver','return'):self.assertEqual(old['routes'][name],new['routes'][name])
        self.assertEqual(new['routes']['deliver']['speeds'],[137]*6+[20])
        self.assertEqual(new['routes']['return']['speeds'],[20]+[137]*5)
        self.assertIn(str(h.HORIZONTAL_CORRECTION),new['source_hashes'])
        self.assertNotIn(str(h.HORIZONTAL_SPEED6),new['source_hashes'])

    def test_horizontal_fifty_default_changes_only_horizontal_speeds(self):
        old=h.geometry(revision=5);new=h.geometry()
        for name in old['routes']:
            self.assertEqual(old['routes'][name]['points'],new['routes'][name]['points'])
            self.assertEqual(old['routes'][name]['expected'],new['routes'][name]['expected'])
            if name not in ('deliver','return'):self.assertEqual(old['routes'][name],new['routes'][name])
        self.assertEqual(new['routes']['deliver']['speeds'],[137]*6+[50])
        self.assertEqual(new['routes']['return']['speeds'],[50]+[137]*5)
        added={str(h.HORIZONTAL_SPEED6),str(h.HORIZONTAL_SPEED7)}
        self.assertTrue(added<=set(new['source_hashes']))
        self.assertEqual({k:v for k,v in new['source_hashes'].items() if k not in added},old['source_hashes'])

    def test_changed_revision7_speed_rejected_before_motion(self):
        data=json.loads(h.HORIZONTAL_SPEED7.read_bytes());data['horizontal_entry_speed']=70
        candidate=Path(self.tmp.name)/'changed7.json';candidate.write_text(json.dumps(data))
        with patch.object(h,'HORIZONTAL_SPEED7',candidate):
            with self.assertRaisesRegex(Exception,'revision7 changed'):h.geometry()
        self.assertEqual(self.calls,[])

    def test_horizontal_seventy_changes_only_horizontal_speeds(self):
        old=h.geometry(revision=5);new=h.geometry(revision=6)
        for name in old['routes']:
            self.assertEqual(old['routes'][name]['points'],new['routes'][name]['points'])
            self.assertEqual(old['routes'][name]['expected'],new['routes'][name]['expected'])
            if name not in ('deliver','return'):self.assertEqual(old['routes'][name],new['routes'][name])
        self.assertEqual(new['routes']['deliver']['speeds'],[137]*6+[70])
        self.assertEqual(new['routes']['return']['speeds'],[70]+[137]*5)
        self.assertIn(str(h.HORIZONTAL_CORRECTION),new['source_hashes'])
        self.assertIn(str(h.HORIZONTAL_SPEED6),new['source_hashes'])
        self.assertEqual({k:v for k,v in new['source_hashes'].items() if k!=str(h.HORIZONTAL_SPEED6)},old['source_hashes'])

    def test_changed_revision6_speed_rejected_before_motion(self):
        data=json.loads(h.HORIZONTAL_SPEED6.read_bytes());data['horizontal_withdrawal_speed']=137
        candidate=Path(self.tmp.name)/'changed6.json';candidate.write_text(json.dumps(data))
        with patch.object(h,'HORIZONTAL_SPEED6',candidate):
            with self.assertRaisesRegex(Exception,'revision6 changed'):h.geometry()
        self.assertEqual(h.geometry(revision=5)['routes']['return']['speeds'][0],20)
        self.assertEqual(self.calls,[])

    def test_changed_correction_rejected_before_motion(self):
        data=json.loads(h.CORRECTION.read_bytes());data['endpoint_x_mm']=300
        candidate=Path(self.tmp.name)/'changed.json';candidate.write_text(json.dumps(data))
        with patch.object(h,'CORRECTION',candidate):
            with self.assertRaisesRegex(Exception,'correction changed'):h.geometry()
        self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()
