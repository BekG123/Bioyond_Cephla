import json
import tempfile
import unittest
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hotel_slot1_retrieval as h
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
        self.correction_failure=None
        for p in (patch.object(state_module,'native',read),patch.object(h,'OUTPUT',Path(self.tmp.name)),
                  patch.object(h,'verify',self.correct_holder)):
            p.start();self.addCleanup(p.stop)
    def correct_holder(self,service,run,correct=False):
        self.calls.append(('holder_correction',correct))
        if self.correction_failure:raise RuntimeError(self.correction_failure)
        self.axes['E2']=1.77;return [1.77,1.77,1.77]
    def jaw(self,target,speed):
        self.axes['E1']=target;self.calls.append(('jaw',target,speed));return {'ok':True}
    def queue(self,run,start,joints,points,cfg,speed,monitor,**kw):
        name=kw['hotel_route'].removeprefix(h.PREFIX);self.calls.append(('queue',name));monitor()
        self.s['pose_mm']=deepcopy(points[-1]);self.s['joints']=deepcopy(self.g['routes'][name]['expected']);monitor()
        return {'ok':True}
    def test_complete_order_and_release_only_after_seating(self):
        p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):result=h.execute(self.run,self.svc,self.cfg,p)
        self.assertTrue(result['ok'])
        self.assertEqual(self.calls,[('queue','approach'),('jaw',4.9,10),('jaw',3.9,5),('queue','lift'),
            ('queue','return'),('queue','seat'),('jaw',28,5),('queue','clear')])
    def test_drifted_holder_corrected_once_before_any_arm_motion(self):
        self.axes['E2']=1.873;p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):result=h.execute(self.run,self.svc,self.cfg,p)
        self.assertTrue(result['ok'])
        self.assertEqual(self.calls[:2],[('holder_correction',True),('queue','approach')])
        self.assertEqual(self.calls.count(('holder_correction',True)),1)
        record=json.loads(Path(result['record']).read_text());self.assertEqual(record['holder_readings'],[1.77,1.77,1.77])

    def test_accepted_holder_gets_no_correction(self):
        for angle in (1.745,1.77,1.815):
            self.calls.clear();self.axes.update(E1=7.,E2=angle);self.s['pose_mm']=deepcopy(self.g['home'])
            self.s['joints']=deepcopy(reference()[0]['start_joints']);p=h.preview(self.svc,self.cfg)
            with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):h.execute(self.run,self.svc,self.cfg,p)
            self.assertNotIn(('holder_correction',True),self.calls)

    def test_holder_beyond_correction_bound_refused_before_motion(self):
        self.axes['E2']=3.9
        with self.assertRaisesRegex(Exception,'original accepted orientation'):h.preview(self.svc,self.cfg)
        self.assertEqual(self.calls,[])

    def test_failed_holder_correction_stops_before_approach(self):
        self.axes['E2']=1.873;self.correction_failure='E2 correction did not verify';p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):
            with self.assertRaisesRegex(Exception,'did not verify'):h.execute(self.run,self.svc,self.cfg,p)
        self.assertNotIn(('queue','approach'),self.calls)
        self.assertEqual(self.calls,[('holder_correction',True),('program','stop')])

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
        self.assertEqual(r['lift']['speeds'],[5]);self.assertEqual(r['approach']['speeds'][-2:],[137,50])
        self.assertAlmostEqual(end['X'],290.878)
        self.assertEqual(r['return']['speeds'],[50,137,137,137,137,137])
        self.assertEqual(r['seat']['speeds'],[5,5])  # contact phases stay slow
    def test_route_speed_and_owner_bound(self):
        p=h.preview(self.svc,self.cfg);owner=h.RetrievalService(self.svc,p);r=self.g['routes']['approach']
        h.prepare_for_service(owner,h.PREFIX+'approach',p['start'],p['joints'],r['points'],self.cfg,self.g['envelope'],r['speeds'])
        with self.assertRaises(Exception):h.prepare_for_service(owner,h.PREFIX+'approach',p['start'],p['joints'],r['points'],self.cfg,self.g['envelope'],[137]*6)
        with self.assertRaises(Exception):h.prepare_for_service(self.svc,h.PREFIX+'approach',p['start'],p['joints'],r['points'],self.cfg,self.g['envelope'],r['speeds'])
        self.assertEqual(self.calls,[])
    def test_reported_home_offset_passes_real_preview_and_route_validation(self):
        observed=dict(X=312.073,Y=-66.385,Z=105.69,Rz=89.698)
        joints=h.check_path(self.s['pose_mm'],observed,self.s['joints'],self.cfg,None)
        joints['J1']=self.s['joints']['J1']+observed['Z']-self.s['pose_mm']['Z']
        self.s.update(pose_mm=observed,joints=joints)
        p=h.preview(self.svc,self.cfg)
        self.assertEqual(p['start'],observed)
        owner=h.RetrievalService(self.svc,p);r=self.g['routes']['approach']
        h.prepare_for_service(owner,h.PREFIX+'approach',p['start'],p['joints'],r['points'],self.cfg,self.g['envelope'],r['speeds'])
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue):
            result=h.execute(self.run,self.svc,self.cfg,p)
        self.assertTrue(result['ok'])
        self.assertEqual(self.calls[0],('queue','approach'))

    def test_home_offset_does_not_relax_contact_start_or_plan_drift(self):
        p=h.preview(self.svc,self.cfg);owner=h.RetrievalService(self.svc,p)
        for name in ('approach','lift','return','seat','clear'):
            with self.subTest(name=name):
                r=self.g['routes'][name];start=dict(r['start'],X=r['start']['X']+.1)
                owner.expected_e1=r['e1']
                with self.assertRaisesRegex(Exception,'Pose mismatch'):
                    h.prepare_for_service(owner,h.PREFIX+name,start,p['joints'],r['points'],self.cfg,self.g['envelope'],r['speeds'])

    def test_actual_approach_ik_failure_blocks_before_dispatch(self):
        # Geometry is validated separately; isolate the check of live feedback.
        with patch.object(h,'geometry',return_value=self.g),patch.object(h,'checked',side_effect=ValueError('actual approach blocked')):
            with self.assertRaisesRegex(ValueError,'actual approach blocked'):h.preview(self.svc,self.cfg)
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

    def holder_commands(self,failure=None):
        self.token=None
        def command(values,job,timeout):
            self.calls.append(('holder',job))
            self.token=int(values[7])
            if job==14:
                if failure=='timeout':raise TimeoutError('unknown holder state')
                if failure!='arrival':self.axes['E2']=values[9]
            if job==13 and failure=='stop':self.run.stopped=lambda:True
            return {'ok':True}
        self.svc._locked=lambda fn:fn()
        self.svc._hostpoint=command
        self.svc.robot=SimpleNamespace(get_sys_var_i=lambda keys:{7:self.token,8:250104})

    def drifted_queue(self,*args,**kw):
        result=self.queue(*args,**kw)
        if kw['hotel_route']==h.PREFIX+'seat':self.axes['E2']=1.7383376785598994
        return result

    def test_reported_seating_drift_corrected_only_after_release_and_clearance(self):
        self.holder_commands();p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.drifted_queue),patch.object(h.time,'sleep'):
            result=h.execute(self.run,self.svc,self.cfg,p,restore_holder_for_handoff=True)
        self.assertTrue(result['ok'])
        self.assertEqual(self.calls[-3:],[('queue','clear'),('holder',13),('holder',14)])
        self.assertLess(self.calls.index(('jaw',28,5)),self.calls.index(('holder',14)))
        record=json.loads(Path(result['record']).read_bytes())
        self.assertEqual(record['final_native']['external_axes']['E2'],1.77)
        step=record['steps'][-1]
        self.assertTrue(step['correction_sent']);self.assertEqual(step['status'],'completed')
        self.assertIn(1.7383376785598994,step['samples'])
        import hotel_cellvis_handoff as handoff
        from hotel_squid_composition import profile_binding
        with patch.object(handoff,'FOLDER',Path(self.tmp.name)/'handoffs'):
            source=handoff.create(result['record'],profile_binding('Cellvis P24-1.5H-N',1),handoff.scanner_reference())
            verified=handoff.validate_source(source,json.loads(source.read_bytes()))
        self.assertEqual(verified['station_clearance']['Z'],105.72)

    def test_handoff_angle_already_accepted_sends_no_holder_command(self):
        self.holder_commands();p=h.preview(self.svc,self.cfg)
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.queue),patch.object(h.time,'sleep'):
            result=h.execute(self.run,self.svc,self.cfg,p,restore_holder_for_handoff=True)
        self.assertTrue(result['ok']);self.assertFalse(any(c[0]=='holder' for c in self.calls))

    def test_failed_or_stopped_correction_never_retries_or_completes_receipt(self):
        for failure in ('timeout','arrival','stop'):
            with self.subTest(failure=failure):
                self.axes.update(E1=7,E2=1.77);self.s['pose_mm']=deepcopy(self.g['home'])
                self.calls=[];self.run.stopped=lambda:False;self.holder_commands(failure)
                p=h.preview(self.svc,self.cfg)
                with patch('trajectory_queue.LuaTrajectory.execute',side_effect=self.drifted_queue),patch.object(h.time,'sleep'):
                    with self.assertRaises(Exception):h.execute(self.run,self.svc,self.cfg,p,restore_holder_for_handoff=True)
                self.assertEqual(self.calls.count(('holder',14)),0 if failure=='stop' else 1)
                latest=max(Path(self.tmp.name).glob('*.json'),key=lambda path:path.stat().st_mtime_ns)
                self.assertEqual(json.loads(latest.read_bytes())['status'],'stopped_or_uncertain')

    def test_correction_requires_clearance_open_jaws_and_bounded_drift(self):
        self.holder_commands();self.axes.update(E1=28,E2=1.7383376785598994)
        for change in ('pose','jaw','angle','moving'):
            with self.subTest(change=change):
                self.s['pose_mm']=deepcopy(self.g['home']);self.axes.update(E1=28,E2=1.7383376785598994)
                if change=='pose':self.s['pose_mm']['Z']-=30
                if change=='jaw':self.axes['E1']=7
                if change=='angle':self.axes['E2']=1.2
                patches=patch.object(h,'state',side_effect=RuntimeError('moving')) if change=='moving' else patch.object(h.time,'sleep')
                with patches:
                    with self.assertRaises(Exception):h.settle_released_holder(self.run,self.svc,self.cfg,self.g,{'steps':[]},lambda:None)
                self.assertFalse(any(c[0]=='holder' for c in self.calls))


if __name__=='__main__':unittest.main()
