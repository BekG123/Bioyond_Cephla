from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from unittest import TestCase,main
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_home_hamilton_exchange as fixtures
import home_squid_transfer as hs
import hamilton_holder_dropoff as drop
from trajectory_queue import prepare_points


class HomeSquidTests(TestCase):
    def setUp(self):
        self.f=fixtures.ExchangeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;self.g=hs.geometry()
        saved=json.loads((hs.exchange.ROOT/'work/home_squid_live_start.json').read_bytes())
        f.state=deepcopy(saved['state']['robot']);f.state['external_axes']['E1']=28
        f.angle=saved['native']['external_axes']['E2'];self.source=Path(f.tmp.name)/'source.json'
        self.source.write_text(json.dumps(dict(status=drop.STATUSES['finish_home'],finished_at=time.time(),final=f.state)))
        for p in (patch.object(drop,'FOLDER',Path(f.tmp.name)),patch.object(hs,'FOLDER',Path(f.tmp.name)/'output'),patch.object(hs,'LuaTrajectory')):
            p.start();self.addCleanup(p.stop)
        hs.LuaTrajectory.return_value.capability.return_value=dict(available=True,version=220109)
        hs.LuaTrajectory.return_value.execute.side_effect=self.queue
        self.gripper=Mock();self.gripper._configuration.return_value=({},'bound')
        def grip(run,receipt):
            self.assertEqual(receipt['descent_result']['descent_correction']['endpoint'],self.g['profile']['candidate_endpoint'])
            f.state['external_axes']['E1']=3.9;return {'ok':True}
        self.gripper.execute.side_effect=grip

    def queue(self,run,start,joints,points,cfg,speed,progress,**flags):
        prepare_points(start,joints,points,cfg,reviewed=True,home_transit=flags.get('home_transit',False),squid_queue=flags.get('squid_queue',False))
        if flags.get('squid_queue'):
            self.assertEqual(flags['segment_speeds'],hs.validate_route(start,points)[1]);self.assertEqual(speed,137)
            q=hs.check_route(start,points,joints,cfg,self.f.svc.envelope)
        else:q=hs.checked(start,points,joints,cfg,self.f.svc.envelope)
        self.f.moves.append(deepcopy(points));self.f.state['joints']=q;self.f.state['pose_mm']=deepcopy(points[-1]);progress('done',1,1)
        return {'ok':True}

    def planned(self):return hs.plan(self.f.svc,self.g['cfg'],self.source)

    def test_full_transfer_restores_holder_and_stops_held_at_current_squid_endpoint(self):
        result=hs.execute(self.f.run,self.f.svc,self.g['cfg'],self.planned(),self.gripper)
        self.assertTrue(result['ok']);self.assertEqual(self.f.rotations,[1.77])
        self.assertEqual(self.f.state['pose_mm'],dict(X=223.94,Y=373.76,Z=266.77,Rz=88.34))
        self.assertEqual(self.f.state['external_axes']['E1'],3.9)
        self.assertEqual(len(self.f.moves),5)
        self.f.svc.move_gripper.assert_not_called() # Existing ReferenceGrip owns closure; no release.

    def test_rotation_outside_band_stops_before_descent(self):
        p=self.planned();original=self.f.host
        def wrong(params,mode,timeout):
            result=original(params,mode,timeout)
            if mode==14:self.f.angle=1.74
            return result
        self.f.svc._hostpoint.side_effect=wrong
        with self.assertRaisesRegex(hs.TransferError,'angle changed'):hs.execute(self.f.run,self.f.svc,self.g['cfg'],p,self.gripper)
        self.assertEqual(self.f.moves,[]);self.gripper.execute.assert_not_called()

    def test_failed_grip_never_lifts_or_travels(self):
        self.gripper.execute.side_effect=None;self.gripper.execute.return_value={'ok':False}
        with self.assertRaisesRegex(hs.TransferError,'grip uncertain'):hs.execute(self.f.run,self.f.svc,self.g['cfg'],self.planned(),self.gripper)
        self.assertEqual(self.f.state['pose_mm'],self.g['seat']);self.assertEqual(len(self.f.moves),3)

    def test_fresh_calibration_starts_long_side_without_holder_rotation(self):
        self.f.state['joints']=hs.checked(self.f.state['pose_mm'],[self.g['clearance']],self.f.state['joints'],self.g['cfg'],self.f.svc.envelope)
        self.f.state['pose_mm']=deepcopy(self.g['clearance']);self.f.angle=1.77
        self.source.write_text(json.dumps(dict(status='calibration_completed_at_HOME')))
        hs.exchange.calibration_evidence.return_value=({'final':deepcopy(self.f.state)},self.f.binding)
        p=self.planned();self.assertFalse(p['rotate_holder'])
        result=hs.execute(self.f.run,self.f.svc,self.g['cfg'],p,self.gripper)
        self.assertTrue(result['ok']);self.assertEqual(self.f.rotations,[])
        self.assertEqual(len(self.f.moves),4)

    def test_calibration_source_rejects_wrong_holder_angle(self):
        self.f.state['pose_mm']=deepcopy(self.g['clearance'])
        self.source.write_text(json.dumps(dict(status='calibration_completed_at_HOME')))
        hs.exchange.calibration_evidence.return_value=({'final':deepcopy(self.f.state)},self.f.binding)
        with self.assertRaisesRegex(hs.TransferError,'orientation'):self.planned()

    def test_mixed_speed_route_cannot_change_destination(self):
        points=deepcopy(self.g['points']);points[-1]['Z']-=1
        with self.assertRaises(hs.TransferError):hs.validate_route(self.g['proof'],points)

    def test_live_grip_context_matches_existing_configuration(self):
        from pick_and_hold.Grip.reference_grip import configuration,plan_for_reference
        from projected_pickup import ProjectedPickup
        obj=ProjectedPickup.__new__(ProjectedPickup)
        context=dict(plate_profile_id=self.g['profile']['id'],descent_correction=dict(endpoint=self.g['profile']['candidate_endpoint'],profile_sha256=self.g['profile_sha256']))
        ref,digest=obj.grip_configuration(context,*configuration())
        p=plan_for_reference(ref)
        self.assertEqual(p['target_e1_mm'],3.9);self.assertEqual(p['commands'][-1]['target_e1_mm'],3.9)

    def test_return_exact_reverse_slow_departure_and_separate_home_release(self):
        result=hs.execute(self.f.run,self.f.svc,self.g['cfg'],self.planned(),self.gripper)
        p=hs.plan_return(self.f.svc,self.g['cfg'],result['record'])
        self.assertEqual(p['speeds'],[5,137,137,137])
        self.assertEqual(p['points'],list(reversed([self.g['proof']]+self.g['points'][:-1])))
        result=hs.execute_return(self.f.run,self.f.svc,self.g['cfg'],p)
        self.assertEqual(result['status'],'returned_held_at_HOME_seat')
        self.assertEqual(self.f.moves[-1],[hs.seating_plan(self.g['seat'])['pose']])
        self.assertEqual(self.f.state['pose_mm'],hs.seating_plan(self.g['seat'])['pose'])
        self.f.svc.move_gripper.assert_not_called()
        p=hs.plan_return(self.f.svc,self.g['cfg'],result['record'],'release_home')
        before=deepcopy(self.g['seat']);jaw=self.f.svc.move_gripper.side_effect
        def verify_release(target,speed):
            self.assertEqual(self.f.state['pose_mm'],dict(before,Z=round(before['Z']-1,3)))
            return jaw(target,speed)
        self.f.svc.move_gripper.side_effect=verify_release
        self.assertEqual(p['home_seating']['speed'],5)
        count=len(self.f.moves);result=hs.execute_return(self.f.run,self.f.svc,self.g['cfg'],p)
        self.assertEqual(len(self.f.moves),count+1) # Empty rise only; release adds no descent.
        self.assertEqual(result['status'],'plate_released_at_HOME_clearance')
        self.assertEqual(self.f.jaws,[28])
        self.assertEqual(self.g['seat'],before)
        self.assertEqual(self.f.state['pose_mm'],self.g['clearance'])

    def test_failed_home_lowering_does_not_release_or_rise(self):
        r=hs.execute(self.f.run,self.f.svc,self.g['cfg'],self.planned(),self.gripper)
        p=hs.plan_return(self.f.svc,self.g['cfg'],r['record'])
        original=hs.LuaTrajectory.return_value.execute.side_effect
        def fail(run,start,joints,points,*args,**kwargs):
            if points==[hs.seating_plan(self.g['seat'])['pose']]:raise TimeoutError('seating uncertain')
            return original(run,start,joints,points,*args,**kwargs)
        hs.LuaTrajectory.return_value.execute.side_effect=fail
        with self.assertRaisesRegex(TimeoutError,'seating uncertain'):
            hs.execute_return(self.f.run,self.f.svc,self.g['cfg'],p)
        self.f.svc.move_gripper.assert_not_called();self.assertEqual(self.f.state['external_axes']['E1'],3.9)
        self.assertEqual(self.f.state['pose_mm'],self.g['proof'])

    def test_modified_home_lowering_speed_is_rejected(self):
        r=hs.execute(self.f.run,self.f.svc,self.g['cfg'],self.planned(),self.gripper)
        r=hs.execute_return(self.f.run,self.f.svc,self.g['cfg'],hs.plan_return(self.f.svc,self.g['cfg'],r['record']))
        p=hs.plan_return(self.f.svc,self.g['cfg'],r['record'],'release_home');p['home_seating']['speed']=137
        count=len(self.f.moves)
        with self.assertRaisesRegex(hs.TransferError,'plan changed'):
            hs.execute_return(self.f.run,self.f.svc,self.g['cfg'],p)
        self.assertEqual(len(self.f.moves),count);self.f.svc.move_gripper.assert_not_called()

    def test_old_seating_receipt_cannot_trigger_extra_lowering_or_release(self):
        r=hs.execute(self.f.run,self.f.svc,self.g['cfg'],self.planned(),self.gripper)
        r=hs.execute_return(self.f.run,self.f.svc,self.g['cfg'],hs.plan_return(self.f.svc,self.g['cfg'],r['record']))
        path=Path(r['record']);data=json.loads(path.read_bytes())
        data['plan']['home_seating'].pop('mode');path.write_text(json.dumps(data))
        count=len(self.f.moves)
        with self.assertRaisesRegex(hs.TransferError,'fresh return'):
            hs.plan_return(self.f.svc,self.g['cfg'],path,'release_home')
        self.assertEqual(len(self.f.moves),count);self.f.svc.move_gripper.assert_not_called()

    def test_return_timeout_never_seats_or_releases_and_cannot_replay(self):
        result=hs.execute(self.f.run,self.f.svc,self.g['cfg'],self.planned(),self.gripper)
        p=hs.plan_return(self.f.svc,self.g['cfg'],result['record'])
        hs.LuaTrajectory.return_value.execute.side_effect=TimeoutError('uncertain')
        with self.assertRaises(TimeoutError):hs.execute_return(self.f.run,self.f.svc,self.g['cfg'],p)
        self.f.svc.move_gripper.assert_not_called()
        with self.assertRaisesRegex(hs.TransferError,'already attempted'):hs.plan_return(self.f.svc,self.g['cfg'],result['record'])


if __name__=='__main__':main()
