"""Offline HOME exchange: real IK/reference validation, simulated actuators."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import home_hamilton_exchange as exchange
from short_side_hover_transfer import reference


class ExchangeTests(TestCase):
    def setUp(self):
        self.route,_,self.grip=reference('04')
        batch=json.loads((exchange.ROOT/'operator_ui/reports/pickup_holder/5_cycles_a3dec023b28846f4b7767bb0b7535702/run.json').read_bytes())
        self.state=deepcopy(batch['cycles'][-1]['phases'][-1]['state']['robot'])
        self.state['external_axes']['E1']=28
        self.angle=1.77;self.moves=[];self.jaws=[];self.rotations=[]
        self.svc=Mock()
        self.svc.status.side_effect=lambda:deepcopy(self.state)
        self.svc.pose_mm.side_effect=lambda:deepcopy(self.state['pose_mm'])
        self.svc.envelope={k:(self.route['global_envelope'][k]['min'],self.route['global_envelope'][k]['max']) for k in ('X','Y','Z')}
        self.svc.envelope_enabled=True;self.svc._preflight.return_value=None
        self.svc._locked.side_effect=lambda fn:fn()
        self.svc._hostpoint.side_effect=self.host
        self.svc.move_gripper.side_effect=self.jaw
        self.run=Mock();self.run.stopped.return_value=False
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.binding=dict(calibration_record='fake',calibration_sha256='bound',clearance_record='fake',clearance_sha256='bound')
        self.patches=[patch.object(exchange,'native',side_effect=self.native),
            patch.object(exchange,'calibration_evidence',return_value=({'final':deepcopy(self.state)},self.binding)),
            patch.object(exchange,'FOLDER',Path(self.tmp.name)),patch.object(exchange.time,'sleep'),
            patch.object(exchange,'LuaTrajectory')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        exchange.LuaTrajectory.return_value.execute.side_effect=self.queue

    def native(self,svc):
        return dict(moving=False,external_axes=dict(E1=self.state['external_axes']['E1'],E2=self.angle))

    def host(self,params,mode,timeout):
        if mode==13:self.svc.robot.get_sys_var_i.return_value={7:params[7],8:250104}
        elif mode==14:self.rotations.append(params[9]);self.angle=params[9]
        else:raise AssertionError(mode)
        return {'ok':True}

    def jaw(self,target,speed):
        self.assertEqual(speed,10 if target in (26,4.9) else 5)
        self.jaws.append(target);self.state['external_axes']['E1']=target
        return {'ok':True}

    def queue(self,run,start,joints,points,cfg,speed,progress,**flags):
        self.moves.append(dict(points=deepcopy(points),speed=speed,flags=flags))
        if flags.get('hamilton_short_side'):
            direction=flags['hamilton_short_side'].split('_')[-1]
            self.assertEqual(points,self.route['routes'][direction]['points'])
            self.assertEqual(flags['segment_speeds'],self.route['routes'][direction]['segment_speeds'])
        self.state['pose_mm']=deepcopy(points[-1]);progress('complete',1,1)
        return {'ok':True}

    def planned(self):return json.loads(json.dumps(exchange.plan(self.svc,self.route['config'],'fake')))

    def test_real_ik_validates_connection_and_both_accepted_routes(self):
        p=self.planned()
        self.assertFalse(p['idle_travel'])
        self.assertEqual(p['holder_target_degrees'],90.71661229181757)
        self.svc._hostpoint.assert_not_called()

    def test_complete_roundtrip_release_and_clearance_no_idle(self):
        result=exchange.execute(self.run,self.svc,self.route['config'],self.planned())
        self.assertTrue(result['ok']);self.assertEqual(result['payload'],'empty')
        self.assertEqual(self.jaws,[26,25,28])
        self.assertEqual(len(self.rotations),1)
        self.assertEqual([m['speed'] for m in self.moves],[5,137,5,137,137,5,137])
        self.assertEqual(self.moves[-2]['points'],[dict(self.grip['descent_endpoint'],Z=round(self.grip['descent_endpoint']['Z']-1,3))])
        self.assertAlmostEqual(result['pose_mm']['Z'],104.37)
        self.assertTrue(all(p['Y']<0 for m in self.moves for p in m['points']))

    def test_pending_incremental_plan_cannot_dispatch_after_closure_change(self):
        p=self.planned();p.pop('closure_policy')
        with self.assertRaisesRegex(exchange.TransferError,'closure_policy'):
            exchange.execute(self.run,self.svc,self.route['config'],p)
        self.assertEqual(self.moves,[]);self.assertEqual(self.jaws,[])

    def test_delivery_only_stops_held_at_hamilton_without_reverse_or_release(self):
        plan=exchange.plan(self.svc,self.route['config'],'fake',delivery_only=True)
        result=exchange.execute(self.run,self.svc,self.route['config'],plan)
        self.assertEqual(result['station'],'Hamilton')
        self.assertEqual(result['payload'],'held')
        self.assertEqual(self.jaws,[26,25])
        self.assertEqual(self.state['pose_mm'],self.route['routes']['forward']['points'][-1])
        receipt=json.loads(Path(result['record']).read_bytes())
        self.assertEqual(receipt['status'],'at_hamilton_awaiting_support_inspection')
        self.assertEqual(len(self.moves),4)

    def test_failed_fast_approach_does_not_close_final_mm_or_lift(self):
        p=self.planned()
        def fail(target,speed):
            self.assertEqual((target,speed),(26,10))
            self.jaws.append(target)
            return dict(ok=False,error='approach failed')
        self.svc.move_gripper.side_effect=fail
        with self.assertRaisesRegex(exchange.TransferError,'Jaw command failed'):
            exchange.execute(self.run,self.svc,self.route['config'],p)
        self.assertEqual(self.jaws,[26])
        self.assertEqual(self.state['pose_mm'],self.grip['descent_endpoint'])
        self.assertEqual(len(self.moves),2)

    def test_failed_rotation_never_approaches_or_grips(self):
        p=self.planned()
        self.svc._hostpoint.side_effect=lambda params,mode,timeout: {'ok':False}
        with self.assertRaises(exchange.TransferError):exchange.execute(self.run,self.svc,self.route['config'],p)
        self.assertEqual(self.moves,[]);self.assertEqual(self.jaws,[])

    def test_failed_forward_never_runs_reverse_or_release(self):
        p=self.planned();original=self.queue
        def fail(*args,**kwargs):
            if kwargs.get('hamilton_short_side')=='pickup_hover04_forward':raise exchange.TransferError('timeout')
            return original(*args,**kwargs)
        exchange.LuaTrajectory.return_value.execute.side_effect=fail
        with self.assertRaises(exchange.TransferError):exchange.execute(self.run,self.svc,self.route['config'],p)
        self.assertEqual(self.jaws[-1],25)
        self.assertEqual(len(self.moves),3)

    def test_holder_shift_before_return_seating_stops_with_plate_held(self):
        p=self.planned();original=self.queue
        def shift(*args,**kwargs):
            result=original(*args,**kwargs)
            if kwargs.get('hamilton_short_side')=='pickup_hover04_reverse':self.angle+=1
            return result
        exchange.LuaTrajectory.return_value.execute.side_effect=shift
        with self.assertRaises(exchange.TransferError):exchange.execute(self.run,self.svc,self.route['config'],p)
        self.assertEqual(self.jaws[-1],25);self.assertEqual(len(self.moves),5)

    def return_drift(self,delta):
        original=self.queue
        def shift(*args,**kwargs):
            result=original(*args,**kwargs)
            if kwargs.get('hamilton_short_side')=='pickup_hover04_reverse':self.angle+=delta
            return result
        exchange.LuaTrajectory.return_value.execute.side_effect=shift

    def test_small_positive_drift_allows_seating_release_and_clearance(self):
        self.return_drift(.499)
        result=exchange.execute(self.run,self.svc,self.route['config'],self.planned())
        self.assertTrue(result['ok']);self.assertEqual(self.jaws[-1],28)
        self.assertAlmostEqual(result['pose_mm']['Z'],104.37)

    def test_small_negative_drift_allows_seating_release_and_clearance(self):
        self.return_drift(-.499)
        result=exchange.execute(self.run,self.svc,self.route['config'],self.planned())
        self.assertTrue(result['ok']);self.assertEqual(self.jaws[-1],28)

    def test_drift_beyond_new_tolerance_stops_before_seating_and_logs_reading(self):
        self.return_drift(.501);p=self.planned()
        with self.assertRaisesRegex(exchange.TransferError,'tolerance 0.50'):
            exchange.execute(self.run,self.svc,self.route['config'],p)
        self.assertEqual(self.jaws[-1],25);self.assertEqual(len(self.moves),5)
        receipt=json.loads((Path(self.tmp.name)/(p['id']+'.json')).read_text())
        self.assertAlmostEqual(receipt['samples'][-1]['axes']['E2'],self.grip['holder_e2_degrees']+.501)

    def test_rotation_arrival_still_requires_original_tight_tolerance(self):
        original=self.host
        def off_target(params,mode,timeout):
            result=original(params,mode,timeout)
            if mode==14:self.angle+=.11
            return result
        self.svc._hostpoint.side_effect=off_target
        with self.assertRaisesRegex(exchange.TransferError,'tolerance 0.10'):
            exchange.execute(self.run,self.svc,self.route['config'],self.planned())
        self.assertEqual(self.moves,[]);self.assertEqual(self.jaws,[])

    def test_missing_holder_feedback_does_not_bypass_guard(self):
        self.return_drift(float('nan'))
        with self.assertRaises(exchange.TransferError):
            exchange.execute(self.run,self.svc,self.route['config'],self.planned())
        self.assertEqual(self.jaws[-1],25);self.assertEqual(len(self.moves),5)

    def test_old_tolerance_plan_requires_new_preview(self):
        p=self.planned();p.pop('holder_tolerances_deg')
        with self.assertRaisesRegex(exchange.TransferError,'holder_tolerances_deg'):
            exchange.execute(self.run,self.svc,self.route['config'],p)
        self.svc._hostpoint.assert_not_called()

    def test_restore_original_at_idle_with_released_plate(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE);self.angle=self.grip['holder_e2_degrees']
        result=exchange.restore_original(self.run,self.svc)
        self.assertTrue(result['ok']);self.assertTrue(result['motion_sent'])
        self.assertEqual(self.rotations,[1.77]);self.assertEqual(self.moves,[]);self.assertEqual(self.jaws,[])

    def test_restore_original_does_not_rotate_already_ready_holder(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE)
        result=exchange.restore_original(self.run,self.svc)
        self.assertFalse(result['motion_sent']);self.svc._hostpoint.assert_not_called()

    def test_restore_accepts_recorded_cycle_five_arrival_and_three_fresh_samples(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE);self.angle=90.73308670809564
        original=self.host
        def recorded(params,mode,timeout):
            result=original(params,mode,timeout)
            if mode==14:self.angle=1.7658034700381073
            return result
        self.svc._hostpoint.side_effect=recorded
        result=exchange.restore_original(self.run,self.svc)
        self.assertTrue(result['ok']);self.assertEqual(self.rotations,[1.77])
        receipt=json.loads(Path(result['record']).read_text())
        self.assertEqual(len(receipt['samples']),6)
        self.assertEqual([s['axes']['E2'] for s in receipt['samples'][-3:]], [self.angle]*3)

    def test_restore_outside_approved_arrival_band_stops_without_retry(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE);self.angle=90.73308670809564
        original=self.host
        def below(params,mode,timeout):
            result=original(params,mode,timeout)
            if mode==14:self.angle=1.749
            return result
        self.svc._hostpoint.side_effect=below
        with self.assertRaisesRegex(exchange.TransferError,'E2=1.749000'):
            exchange.restore_original(self.run,self.svc)
        self.assertEqual(self.rotations,[1.77]);self.assertEqual(self.moves,[])

    def test_restore_accepts_same_idle_readback_as_ui(self):
        self.state['pose_mm']=dict(X=290.009,Y=62.658,Z=248.003,Rz=-3.823)
        self.angle=self.grip['holder_e2_degrees']
        result=exchange.restore_original(self.run,self.svc)
        self.assertTrue(result['ok']);self.assertEqual(self.rotations,[1.77])
        self.assertEqual(self.state['pose_mm']['Rz'],-3.823)

    def test_restore_refuses_arm_near_holder(self):
        self.angle=self.grip['holder_e2_degrees']
        with self.assertRaises(exchange.TransferError):exchange.restore_original(self.run,self.svc)
        self.svc._hostpoint.assert_not_called()

    def test_restore_refuses_closed_jaws(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE);self.state['external_axes']['E1']=25
        with self.assertRaises(exchange.TransferError):exchange.restore_original(self.run,self.svc)
        self.svc._hostpoint.assert_not_called()

    def test_failed_restore_never_retries(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE);self.angle=self.grip['holder_e2_degrees']
        original=self.host
        def fail(params,mode,timeout):
            if mode==14:raise TimeoutError('uncertain restore')
            return original(params,mode,timeout)
        self.svc._hostpoint.side_effect=fail
        with self.assertRaises(TimeoutError):exchange.restore_original(self.run,self.svc)
        self.assertEqual([c.args[1] for c in self.svc._hostpoint.call_args_list],[13,14])

    def test_restore_negative_angle_from_reported_state(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE);self.angle=-2.161808873492161
        result=exchange.restore_original(self.run,self.svc)
        self.assertTrue(result['ok']);self.assertEqual(self.rotations,[1.77])

    def test_restore_far_angle_in_verified_bounded_segments(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE);self.angle=-360
        result=exchange.restore_original(self.run,self.svc)
        self.assertTrue(result['ok']);self.assertEqual(len(self.rotations),5)
        self.assertEqual(self.rotations[-1],1.77)
        receipt=json.loads(Path(result['record']).read_text())
        self.assertTrue(all(s['status']=='completed' and abs(s['target']-s['origin'])<=90.01 for s in receipt['segments']))
        self.assertEqual(self.moves,[]);self.assertEqual(self.jaws,[])

    def test_second_segment_timeout_prevents_remaining_rotations(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE);self.angle=270
        original=self.host;attempts=[]
        def fail(params,mode,timeout):
            if mode==14:
                attempts.append(params[9])
                if len(attempts)==2:raise TimeoutError('uncertain second segment')
            return original(params,mode,timeout)
        self.svc._hostpoint.side_effect=fail
        with self.assertRaises(TimeoutError):exchange.restore_original(self.run,self.svc)
        self.assertEqual(len(attempts),2);self.assertEqual(len(self.rotations),1)

    def test_all_supported_angle_plans_preserve_published_bounds(self):
        for origin in (-360,-270,-180,-90,-2.162,0,1.77,90.717,180,270,360):
            targets=exchange.holder_restore_targets(origin)
            previous=origin
            for target in targets:
                self.assertLessEqual(abs(target),360)
                self.assertLessEqual(abs(target-previous),89.500001)
                self.assertLess(abs(1.77-target),abs(1.77-previous))
                previous=target
            self.assertEqual(previous,1.77)
        for value in (-360.01,360.01,float('nan'),float('inf'),None,True):
            with self.assertRaises(exchange.TransferError):exchange.holder_restore_targets(value)

    def test_bad_intermediate_arrival_prevents_next_segment(self):
        from repeat_holder_calibration_20261110 import IDLE
        self.state['pose_mm']=deepcopy(IDLE);self.angle=270
        original=self.host
        def bad(params,mode,timeout):
            result=original(params,mode,timeout)
            if mode==14:self.angle+=.2
            return result
        self.svc._hostpoint.side_effect=bad
        with self.assertRaisesRegex(exchange.TransferError,'segment arrival mismatch'):
            exchange.restore_original(self.run,self.svc)
        self.assertEqual(len(self.rotations),1)

    def test_modified_plan_or_closed_start_rejected(self):
        p=self.planned();p['grip']['target_e1_mm']=24
        with self.assertRaises(exchange.TransferError):exchange.execute(self.run,self.svc,self.route['config'],p)
        self.state['external_axes']['E1']=25
        with self.assertRaises(exchange.TransferError):self.planned()
        self.svc._hostpoint.assert_not_called()

if __name__=='__main__':main()
