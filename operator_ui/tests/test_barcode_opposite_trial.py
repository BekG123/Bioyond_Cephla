import tempfile
import time
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock,patch
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import barcode_opposite_side_trial as t
from autonomy import TransferError
REAL_PLAN=t.plan


class OppositeTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pose=dict(X=312.5,Y=-66.3,Z=105.72,Rz=89.84)
        self.state=dict(pose_mm=deepcopy(self.pose),joints={k:0. for k in ('J1','J2','J3','J4')})
        self.axes={'E1':28.,'E2':1.77}
        self.service=Mock();self.service._locked.side_effect=lambda f:f()
        self.service.program.return_value={'ok':True}
        self.service._hostpoint.side_effect=self.host
        self.run=Mock();self.run.stopped.return_value=False
        self.approved=dict(at=time.time(),id='a'*32,source='source.json',source_sha256='hash',implementation_sha256='code',
            start=self.pose,joints=self.state['joints'],e2=1.77,targets=t.holder_restore_targets(1.77,t.TARGET),target=t.TARGET,
            geometry={'clearance':self.pose,'seat':dict(self.pose,Z=75.72)})
        for p in [patch.object(t,'OUTPUT',Path(self.tmp.name)),patch.object(t,'plan',side_effect=lambda *args,**kwargs:deepcopy(self.approved)),
                  patch.object(t,'preflight',side_effect=lambda s:deepcopy(self.state)),
                  patch.object(t,'native',side_effect=lambda s:dict(moving=False,manual=False,drag=False,error=False,emergency=False,external_axes=dict(self.axes)))]:
            p.start();self.addCleanup(p.stop)
        p=patch.object(t,'LuaTrajectory');self.lua=p.start();self.addCleanup(p.stop)
        self.lua.return_value.execute.side_effect=self.queue

    def host(self,params,mode,timeout):
        self.assertEqual(self.axes['E1'],28)
        self.assertEqual(self.state['pose_mm'],self.pose)
        if mode==13:self.service.robot.get_sys_var_i.return_value={7:params[7],8:250104}
        if mode==14:
            self.assertLessEqual(abs(params[9]-params[8]),90.01)
            self.axes['E2']=params[9]
        return {'ok':True}

    def queue(self,run,start,joints,points,cfg,speed,progress,**flags):
        self.assertEqual(self.axes['E2'],self.approved['target'])
        self.state['pose_mm']=deepcopy(points[-1]);progress('motion',100,100)
        return {'ok':True}

    def test_rotates_only_released_then_stops_open_for_centering(self):
        result=t.execute(self.run,self.service,{},self.approved)
        self.assertFalse(result['grip_sent']);self.assertEqual(self.axes['E1'],28)
        self.assertEqual(self.axes['E2'],181.77)
        self.assertEqual(self.state['pose_mm']['Z'],75.72)
        self.service.move_gripper.assert_not_called();self.service.program.assert_not_called()

    def test_held_grip_refused_before_any_rotation(self):
        self.axes['E1']=3.9
        with self.assertRaisesRegex(TransferError,'Released empty'):
            t.execute(self.run,self.service,{},self.approved)
        self.service._hostpoint.assert_not_called();self.lua.return_value.execute.assert_not_called()

    def test_small_readback_variation_preserves_previewed_targets(self):
        fresh=deepcopy(self.approved);fresh['e2']+=.002
        fresh['targets']=t.holder_restore_targets(fresh['e2'],t.TARGET)
        self.axes['E2']=fresh['e2']
        with patch.object(t,'plan',return_value=fresh):
            t.execute(self.run,self.service,{},self.approved)
        targets=[c.args[0][9] for c in self.service._hostpoint.call_args_list if c.args[1]==14]
        self.assertEqual(targets,self.approved['targets'])

    def test_modified_target_refused_before_motion(self):
        self.approved['targets'][0]+=1
        with self.assertRaisesRegex(TransferError,'targets changed'):
            t.execute(self.run,self.service,{},self.approved)
        self.service._hostpoint.assert_not_called()

    def test_shared_hamilton_holder_tolerance_boundaries(self):
        for value in (181.27,181.77,182.27):
            self.axes['E2']=value
            t.snapshot(self.service,self.pose,181.77)
        for value in (181.269,182.271,float('nan'),float('inf')):
            self.axes['E2']=value
            with self.assertRaises(TransferError):
                t.snapshot(self.service,self.pose,181.77)

    def test_failed_segment_not_retried_or_followed_by_descent(self):
        original=self.host
        def fail(params,mode,timeout):
            if mode==14:return {'ok':False,'error':'timeout'}
            return original(params,mode,timeout)
        self.service._hostpoint.side_effect=fail
        with self.assertRaisesRegex(TransferError,'no retry'):
            t.execute(self.run,self.service,{},self.approved)
        self.assertEqual(sum(c.args[1]==14 for c in self.service._hostpoint.call_args_list),1)
        self.lua.return_value.execute.assert_not_called();self.service.program.assert_called_once_with('stop')

    def prepared_pickup(self,target=1.77):
        self.axes['E2']=1.82348187
        self.approved.update(prepare_original=True,e2=1.821,target=target,
            targets=[] if target==1.77 else t.holder_restore_targets(1.77,target))
        self.approved['geometry']['station_clearance']=self.pose

    def test_drift_after_release_receipt_centered_before_any_pickup(self):
        self.prepared_pickup()
        with patch.object(t.time,'sleep'):
            result=t.execute(self.run,self.service,{},self.approved)
        commands=[c.args[0][9] for c in self.service._hostpoint.call_args_list if c.args[1]==14]
        self.assertEqual(commands,[1.77])
        record=__import__('json').loads(Path(result['record']).read_bytes())
        self.assertEqual(record['steps'][0]['kind'],'prepare_original_before_pickup')
        self.assertEqual(self.axes['E1'],28)
        self.assertEqual(self.lua.return_value.execute.call_count,2)

    def test_centering_then_other_side_keeps_bounded_targets(self):
        self.prepared_pickup(t.TARGET)
        with patch.object(t.time,'sleep'):t.execute(self.run,self.service,{},self.approved)
        commands=[c.args[0][9] for c in self.service._hostpoint.call_args_list if c.args[1]==14]
        self.assertEqual(commands,[1.77]+t.holder_restore_targets(1.77,t.TARGET))

    def test_pre_pickup_correction_failure_prevents_approach_without_retry(self):
        self.prepared_pickup();original=self.host
        def failed(params,mode,timeout):
            if mode==14:return {'ok':False,'error':'timeout'}
            return original(params,mode,timeout)
        self.service._hostpoint.side_effect=failed
        with self.assertRaisesRegex(TransferError,'no retry'):t.execute(self.run,self.service,{},self.approved)
        self.assertEqual(sum(c.args[1]==14 for c in self.service._hostpoint.call_args_list),1)
        self.lua.return_value.execute.assert_not_called()

    def test_success_reply_without_correct_angle_blocks_pickup(self):
        self.prepared_pickup();original=self.host
        self.service._hostpoint.side_effect=lambda params,mode,timeout: ({'ok':True} if mode==14 else original(params,mode,timeout))
        with self.assertRaisesRegex(TransferError,'not verified'):t.execute(self.run,self.service,{},self.approved)
        self.assertEqual(sum(c.args[1]==14 for c in self.service._hostpoint.call_args_list),1)
        self.lua.return_value.execute.assert_not_called()

    def test_preparation_blocks_closed_jaws_before_command(self):
        self.prepared_pickup();self.axes['E1']=3.9
        with self.assertRaisesRegex(TransferError,'Released empty'):t.execute(self.run,self.service,{},self.approved)
        self.service._hostpoint.assert_not_called();self.lua.return_value.execute.assert_not_called()

    def test_readonly_plan_accepts_bounded_drift_only_with_explicit_preparation(self):
        source=Path(self.tmp.name)/'hotel_home.json'
        g=dict(cfg={},station_clearance=self.pose,clearance=self.pose,seat=dict(self.pose,Z=75.72))
        self.service.envelope={'X':[200.,450.],'Y':[-250.,380.],'Z':[70.,400.]}
        self.lua.return_value.capability.return_value={'available':True,'version':220109}
        self.axes['E2']=1.82348187
        with patch.object(t,'source_record',return_value=(source,{'final':self.state})),\
                patch('hotel_cellvis_handoff.validate_source',return_value=g),\
                patch.object(t,'sha',return_value='hash'),patch.object(t,'checked',return_value=self.state['joints']),\
                patch.object(t,'prepare_points'):
            p=REAL_PLAN(self.service,{},source,1.77,prepare_original=True)
            self.assertTrue(p['prepare_original']);self.assertEqual(p['targets'],[])
            with self.assertRaisesRegex(TransferError,'no correction included'):REAL_PLAN(self.service,{},source,1.77)
            self.axes['E2']=2.271
            with self.assertRaisesRegex(TransferError,'bounded correction range'):
                REAL_PLAN(self.service,{},source,1.77,prepare_original=True)
        self.service._hostpoint.assert_not_called();self.lua.return_value.execute.assert_not_called()


if __name__=='__main__':unittest.main()
