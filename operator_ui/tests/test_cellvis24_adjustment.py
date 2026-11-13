"""Offline geometry and failure-boundary tests; never accesses hardware."""
import json
import math
import tempfile
from pathlib import Path
import unittest
from copy import deepcopy
from unittest.mock import patch,Mock

import cellvis24_adjustment as a
from autonomy import TransferError


class AdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.ref=a.reference()['raw_target']
        self.seat=a.geometry()['seat']
        self.ms=[dict(target=deepcopy(self.ref),error_xy_mm=[0,0],measured_wells=24,
                      grid_rmse_px=1,corners_preview_px=[[100,100],[500,100],[500,300],[100,300]]) for _ in range(3)]

    def shift(self,x=0,y=0,yaw=0):
        for m in self.ms:
            m['target']['x']+=x;m['target']['y']+=y;m['target']['rz']+=yaw

    def test_identity_and_translation_preserve_height(self):
        p=a.endpoint_from_measurements(self.ms)
        for k in self.seat:self.assertAlmostEqual(p['endpoint'][k],self.seat[k])
        self.shift(.55,.2)
        p=a.endpoint_from_measurements(self.ms)
        self.assertAlmostEqual(p['endpoint']['X'],self.seat['X']+.55)
        self.assertAlmostEqual(p['endpoint']['Y'],self.seat['Y']+.2)
        self.assertEqual(p['endpoint']['Z'],self.seat['Z'])
        self.assertFalse(p['grip_authorized'])
        self.assertFalse(p['profile_changed'])

    def test_rotation_preserves_plate_relative_offset_and_is_not_cumulative(self):
        self.shift(.2,.1,.3)
        p=a.endpoint_from_measurements(self.ms);q=a.endpoint_from_measurements(self.ms)
        self.assertEqual(p,q)
        old=math.hypot(self.seat['X']-self.ref['x'],self.seat['Y']-self.ref['y'])
        new=math.hypot(p['endpoint']['X']-p['measured_target']['x'],p['endpoint']['Y']-p['measured_target']['y'])
        self.assertAlmostEqual(old,new)
        self.assertAlmostEqual(p['endpoint']['Rz'],self.seat['Rz']+.3)

    def test_yaw_wrap_is_small_change(self):
        self.shift(yaw=-359.9)
        self.assertAlmostEqual(a.endpoint_from_measurements(self.ms)['yaw_delta_deg'],.1)

    def test_reject_invalid_grid_unstable_or_nonfinite(self):
        original=deepcopy(self.ms)
        changes=[('measured_wells',19),('grid_rmse_px',9),('grid_rmse_px',float('nan')),
                 ('error_xy_mm',[1,0]),('corners_preview_px',[[float('nan'),0]]*4)]
        for key,value in changes:
            self.ms=deepcopy(original);self.ms[0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises((TransferError,ValueError)):
                a.endpoint_from_measurements(self.ms)
        self.ms=deepcopy(original);self.ms[0]['target']['x']+=.3
        with self.assertRaises(TransferError):a.endpoint_from_measurements(self.ms)

    def test_large_adjustment_rejected_without_widening_fixed_gate(self):
        self.shift(1.1)
        with self.assertRaises(TransferError):a.endpoint_from_measurements(self.ms)
        self.assertEqual(a.reference()['reuse_xy_mm'],.5)
        self.assertEqual(a.reference()['reuse_yaw_deg'],.2)

    def test_saved_failed_repeat_has_valid_bounded_trial_and_real_ik(self):
        path=a.ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/3f0bfe8b02b143309ed28b7883a822fe/run.json'
        if not path.exists():self.skipTest('Local commissioning evidence unavailable')
        d=json.loads(path.read_bytes())
        ms=[b['measurement'] for s in d['steps'] if s['kind']=='vision' for b in s['measurement']['bursts']]
        p=a.endpoint_from_measurements(ms)
        self.assertFalse(p['assessment']['ok'])
        # Recorded camera-arrival joints; never infer them from the endpoint.
        arrival=next(s for s in d['steps'] if s['kind']=='queue')
        state={'pose_mm':a.OBSERVATION,'joints':d['plan']['joints']}
        from home_squid_transfer import checked
        g=a.geometry()
        state['joints']=checked(d['plan']['start'],arrival['points'],state['joints'],g['cfg'],g['envelope'])
        route=a.checked_route(state,g['cfg'],g['envelope'],p)
        self.assertEqual(route['descent'][-1],p['endpoint'])
        self.assertEqual(route['descent_speed'],5)
        with patch.object(a,'checked',side_effect=TransferError('IK rejected')):
            with self.assertRaises(TransferError):a.checked_route(state,g['cfg'],g['envelope'],p)

    def test_preparation_rejects_closed_jaws_and_drag_without_motion(self):
        service=Mock();service.status.return_value=dict(ok=True,connected=True,errors=[])
        run=Mock();run.stopped.return_value=False
        n=dict(moving=False,error=False,emergency=False,drag=False,external_axes={'E1':28,'E2':1.77})
        with patch.object(a,'native',return_value=n):
            a.stationary(service,run)
            n['external_axes']['E1']=3.9
            with self.assertRaises(TransferError):a.stationary(service,run)
            n['external_axes']['E1']=28;n['drag']=True
            with self.assertRaises(TransferError):a.stationary(service,run)
        service.move_gripper.assert_not_called();service.program.assert_not_called()

    def test_queue_monitor_allows_expected_motion_but_still_checks_faults_and_jaws(self):
        service=Mock();service.status.return_value=dict(ok=True,connected=True,errors=[])
        run=Mock();run.stopped.return_value=False
        n=dict(moving=True,error=False,emergency=False,drag=False,external_axes={'E1':28,'E2':1.77})
        with patch.object(a,'native',return_value=n):
            with self.assertRaises(TransferError):a.stationary(service,run)
            a.stationary(service,run,allow_motion=True)
            n['error']=True
            with self.assertRaises(TransferError):a.stationary(service,run,allow_motion=True)
            n['error']=False;n['external_axes']['E1']=3.9
            with self.assertRaises(TransferError):a.stationary(service,run,allow_motion=True)

    def trial_setup(self):
        # Exercise the historical executor offline only. Production entry
        # points are retired after the operator rejected the adjusted fit.
        p=patch.object(a,'require_trial_enabled');p.start();self.addCleanup(p.stop)
        d=json.loads((a.ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/3f0bfe8b02b143309ed28b7883a822fe/run.json').read_bytes())
        g=a.geometry();arrival=next(s for s in d['steps'] if s['kind']=='queue')
        q=a.checked(d['plan']['start'],arrival['points'],d['plan']['joints'],g['cfg'],g['envelope'])
        self.state=dict(pose_mm=deepcopy(a.OBSERVATION),joints=q)
        self.p=dict(start=deepcopy(a.OBSERVATION),joints=deepcopy(q),e2=1.77,cfg=g['cfg'],envelope=g['envelope'],
                    adjustment=a.endpoint_from_measurements(self.ms))
        self.p['route']=a.checked_route(self.state,g['cfg'],g['envelope'],self.p['adjustment'])
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.service=Mock();self.service.envelope=g['envelope']
        self.service.program.return_value=dict(ok=True)
        self.run=Mock();self.run.stopped.return_value=False
        for p in [patch.object(a,'load_proposal',return_value=(self.folder,self.p)),
                  patch.object(a,'stationary',side_effect=lambda *args,**kw:(deepcopy(self.state),dict(external_axes={'E1':28,'E2':1.77}))),
                  patch.object(a,'capture',return_value=dict(bursts=[dict(measurement=m) for m in self.ms])),
                  patch.object(a,'LuaTrajectory')]:
            value=p.start();self.addCleanup(p.stop)
            if p.attribute=='LuaTrajectory':self.lua=value
            if p.attribute=='stationary':self.monitor=value
        self.lua.return_value.capability.return_value=dict(available=True,version=220109)
        def align(*args,**kw):
            self.state['pose_mm']=deepcopy(self.p['route']['alignment'][-1]);return dict(ok=True)
        p=patch('sequences.seq_align',side_effect=align);self.align=p.start();self.addCleanup(p.stop)
        def descend(*args,**kw):
            args[6]('motion',1,100)
            self.assertTrue(self.monitor.call_args.kwargs['allow_motion'])
            self.state['pose_mm']=deepcopy(self.p['adjustment']['endpoint']);return dict(ok=True)
        self.lua.return_value.execute.side_effect=descend

    def test_trial_stops_open_without_grip_and_is_one_use(self):
        self.trial_setup()
        result=a.execute(self.run,self.service,self.p['cfg'],'id',None)
        self.assertEqual(result['status'],'awaiting_centering_inspection')
        self.service.move_gripper.assert_not_called();self.service.program.assert_not_called()
        with self.assertRaises(FileExistsError):a.execute(self.run,self.service,self.p['cfg'],'id',None)
        self.assertEqual(self.align.call_count,1)

    def test_fresh_measurement_shift_prevents_all_motion(self):
        self.trial_setup();self.shift(.25)
        with self.assertRaisesRegex(TransferError,'changed since proposal'):
            a.execute(self.run,self.service,self.p['cfg'],'id',None)
        self.align.assert_not_called();self.lua.return_value.execute.assert_not_called()
        self.service.program.assert_not_called()

    def test_uncertain_alignment_stops_and_never_descends(self):
        self.trial_setup();self.align.side_effect=None;self.align.return_value=dict(ok=True,recovered=True)
        with self.assertRaisesRegex(TransferError,'Uncertain'):
            a.execute(self.run,self.service,self.p['cfg'],'id',None)
        self.lua.return_value.execute.assert_not_called()
        self.service.program.assert_called_once_with('stop')

    def test_retired_trial_cannot_prepare_or_execute(self):
        service=Mock()
        for call in [lambda:a.prepare(None,service,None,None),lambda:a.execute(None,service,None,'old-id',None)]:
            with self.assertRaisesRegex(TransferError,'retired'):call()
        self.assertEqual(service.mock_calls,[])


if __name__=='__main__':unittest.main()
