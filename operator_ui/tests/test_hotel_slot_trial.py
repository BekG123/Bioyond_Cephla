import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import hotel_slot_trial as h
from trajectory_queue import LuaTrajectory
from autonomy import check_path


class HotelTests(unittest.TestCase):
    def setUp(self):
        self.d,_=h.reference();self.cfg=self.d['config']
        q=check_path(self.d['start'],h.ANCHOR,self.d['start_joints'],self.cfg,self.d['envelope'])
        q['J1']=h.ANCHOR['Z']-self.d['start']['Z']+self.d['start_joints']['J1']
        self.s=dict(connected=True,ok=True,errors=[],enabled=False,program_state={'state':'paused'},
            pose_mm=deepcopy(h.ANCHOR),joints=q)
        self.axes={'E1':.02,'E2':1.925};self.calls=[]
        self.svc=SimpleNamespace(status=lambda:deepcopy(self.s),envelope_enabled=True,
            envelope=self.d['envelope'],set_enable=self.enable,program=self.program,_preflight=lambda:None)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for p in (patch.object(h,'OUTPUT',Path(self.tmp.name)),patch.object(h,'native',lambda svc:dict(
            moving=False,error=False,emergency=False,drag=False,manual=False,external_axes=deepcopy(self.axes)))):
            p.start();self.addCleanup(p.stop)
        self.run=SimpleNamespace(stopped=lambda:False,say=Mock())
    def enable(self,value,confirmed):self.calls.append('enable');self.s['enabled']=value;return {'ok':True}
    def program(self,action,force=False):
        self.calls.append(action);self.s['program_state']['state']='running' if action=='start' else 'stopped'
        if action=='start':self.axes['E1']=0
        return {'ok':True}
    def test_preview_readonly_and_both_routes_pass(self):
        p=h.preview(self.svc,self.cfg);owner=h.HotelService(self.svc,p);q=p['joints']
        for name in ('home','path_a'):
            r=p['routes'][name]
            points,q=h.prepare_for_service(owner,name,r['start'],q,r['points'],self.cfg,self.d['envelope'],r['speeds'])
            self.assertEqual(len(points),2 if name=='home' else 3)
        self.assertEqual(self.calls,[])
    def test_changed_pose_jaws_and_points_are_rejected(self):
        p=h.preview(self.svc,self.cfg);self.axes['E1']=3.9
        with self.assertRaises(Exception):h.preview(self.svc,self.cfg)
        self.axes['E1']=0;self.s['pose_mm']['X']+=1
        with self.assertRaises(Exception):h.preview(self.svc,self.cfg)
        r=p['routes']['path_a'];bad=deepcopy(r['points']);bad[-1]['Z']-=5
        with self.assertRaises(Exception):h.prepare_for_service(h.HotelService(self.svc,p),'path_a',r['start'],self.d['start_joints'],bad,self.cfg,self.d['envelope'],r['speeds'])
        self.assertEqual(self.calls,[])
    def test_unbound_service_and_fast_insertion_are_rejected(self):
        p=h.preview(self.svc,self.cfg);r=p['routes']['path_a']
        with self.assertRaises(Exception):h.prepare_for_service(self.svc,'path_a',r['start'],self.d['start_joints'],r['points'],self.cfg,self.d['envelope'],r['speeds'])
        with self.assertRaises(Exception):h.prepare_for_service(h.HotelService(self.svc,p),'path_a',r['start'],self.d['start_joints'],r['points'],self.cfg,self.d['envelope'],[137]*3)
    def test_queue_failure_stops_without_next_phase(self):
        p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',return_value={'ok':False,'error':'test timeout'}) as execute:
            with self.assertRaisesRegex(Exception,'uncertain'):h.execute(self.run,self.svc,self.cfg,p)
        execute.assert_called_once();self.assertEqual(self.calls,['stop','enable','start','stop'])
        receipt=json.loads(next(Path(self.tmp.name).glob('*.json')).read_bytes())
        self.assertEqual(receipt['status'],'stopped_or_uncertain')
    def reverse_pose(self):
        f=self.d['candidates']['compact_three']
        self.s.update(pose_mm=deepcopy(f['points'][-1]),joints=deepcopy(f['validation']['endpoint_joints']),
                      enabled=True,program_state={'state':'running'})
    def test_reverse_exact_segments_speeds_and_home_joints(self):
        self.reverse_pose();p=h.preview(self.svc,self.cfg,'reverse');r=p['routes']['reverse']
        f=self.d['candidates']['compact_three']['points']
        self.assertEqual(r['points'],[f[1],f[0],self.d['start']]);self.assertEqual(r['speeds'],[5,137,137])
        pts,q=h.prepare_for_service(h.HotelService(self.svc,p),'reverse',self.s['pose_mm'],self.s['joints'],r['points'],self.cfg,self.d['envelope'],r['speeds'])
        for k,v in self.d['start_joints'].items():self.assertAlmostEqual(q[k],v,places=2)
        with self.assertRaises(Exception):h.prepare_for_service(h.HotelService(self.svc,p),'reverse',self.s['pose_mm'],self.s['joints'],r['points'],self.cfg,self.d['envelope'],[137]*3)
        self.assertEqual(self.calls,[])
    def test_reverse_no_startup_after_stop(self):
        self.reverse_pose();self.s['program_state']['state']='stopped'
        with self.assertRaisesRegex(Exception,'no automatic startup'):h.preview(self.svc,self.cfg,'reverse')
        self.assertEqual(self.calls,[])
    def test_reverse_failure_stops_without_retry(self):
        self.reverse_pose();p=h.preview(self.svc,self.cfg,'reverse')
        with patch('trajectory_queue.LuaTrajectory.execute',return_value={'ok':False,'error':'timeout'}) as execute:
            with self.assertRaisesRegex(Exception,'uncertain'):h.execute(self.run,self.svc,self.cfg,p)
        execute.assert_called_once();self.assertEqual(self.calls,['stop'])

    def test_one_cycle_starts_home_and_reverses_without_connector(self):
        self.s.update(pose_mm=deepcopy(self.d['start']),joints=deepcopy(self.d['start_joints']),
                      enabled=True,program_state={'state':'running'})
        p=h.preview(self.svc,self.cfg,'cycle');self.assertEqual(list(p['routes']),['path_a','reverse'])
        owner=h.HotelService(self.svc,p);q=self.s['joints']
        for phase in ('path_a','reverse'):
            r=p['routes'][phase]
            _,q=h.prepare_for_service(owner,phase,r['start'],q,r['points'],self.cfg,self.d['envelope'],r['speeds'])
        phases=[]
        def queued(run,start,joints,points,cfg,speed,monitor,**kw):
            phases.append(kw['hotel_route'])
            self.s['pose_mm']=deepcopy(points[-1]);self.s['joints']=deepcopy(p['routes'][kw['hotel_route']]['expected'])
            return {'ok':True}
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=queued):
            result=h.execute(self.run,self.svc,self.cfg,p)
        self.assertEqual(phases,['path_a','reverse']);self.assertEqual(self.calls,[])
        self.assertEqual(json.loads(Path(result['record']).read_bytes())['status'],'completed_empty_slot1_cycle')
    def test_cycle_wrong_start_or_stopped_controller_rejected(self):
        with self.assertRaises(Exception):h.preview(self.svc,self.cfg,'cycle')
        self.s.update(pose_mm=deepcopy(self.d['start']),joints=deepcopy(self.d['start_joints']))
        with self.assertRaisesRegex(Exception,'no automatic startup'):h.preview(self.svc,self.cfg,'cycle')
        self.assertEqual(self.calls,[])

    def test_queue_mixed_profile_rejected_before_dispatch(self):
        p=h.preview(self.svc,self.cfg);r=p['routes']['path_a']
        with self.assertRaisesRegex(Exception,'pinned empty-arm'):
            LuaTrajectory(h.HotelService(self.svc,p)).execute(self.run,r['start'],self.d['start_joints'],r['points'],self.cfg,137,Mock(),
                reviewed=True,segment_speeds=r['speeds'],hotel_route='path_a',scanner_empty=True)
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
