"""Real reference IK; simulated actuators for separately inspected drop-off phases."""
from copy import deepcopy
import json
from pathlib import Path
import time
from unittest import TestCase, main
from unittest.mock import patch
import test_home_hamilton_exchange as fixtures
import hamilton_holder_dropoff as drop


class DropoffTests(TestCase):
    def setUp(self):
        self.fixture=fixtures.ExchangeTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        source=drop.exchange.ROOT/'operator_ui/reports/plate_session/hamilton_exchanges/fa1a095a1c414820ad23b1b5220e4b3a.json'
        self.data=json.loads(source.read_bytes())
        f.state=deepcopy(self.data['final']);f.state['external_axes']['E1']=28
        f.angle=f.grip['holder_e2_degrees']
        self.source=Path(f.tmp.name)/'source.json'
        self.data['finished_at']=time.time();self.source.write_text(json.dumps(self.data))
        for p in (patch.object(drop,'FOLDER',Path(f.tmp.name)/'dropoffs'),patch.object(drop,'LuaTrajectory')):
            p.start();self.addCleanup(p.stop)
        original=f.queue
        def queue(run,start,joints,points,cfg,speed,progress,**flags):
            q=deepcopy(joints);previous=start;offset=q['J1']-start['Z']
            if flags.get('hamilton_short_side'):
                q=drop.validate_route(start,points,q,cfg,f.svc.envelope,flags['hamilton_short_side'])
            else:
                for point in points:
                    q=drop.check_path(previous,point,q,cfg,f.svc.envelope);q['J1']=point['Z']+offset;previous=point
            f.state['joints']=q
            return original(run,start,joints,points,cfg,speed,progress,**flags)
        drop.LuaTrajectory.return_value.execute.side_effect=queue

    def phase(self,phase,source=None):
        f=self.fixture
        p=drop.plan(f.svc,f.route['config'],phase,str(source or self.source))
        return drop.execute(f.run,f.svc,f.route['config'],p)

    def test_release_accepts_real_delivery_only_exchange_receipt(self):
        other=fixtures.ExchangeTests();other.setUp();self.addCleanup(other.doCleanups)
        original=other.queue
        def queue(run,start,joints,points,cfg,speed,progress,**flags):
            q=deepcopy(joints);previous=start;offset=q['J1']-start['Z']
            if flags.get('hamilton_short_side'):
                q=drop.validate_route(start,points,q,cfg,other.svc.envelope,flags['hamilton_short_side'])
            else:
                for point in points:
                    q=drop.check_path(previous,point,q,cfg,other.svc.envelope);q['J1']=point['Z']+offset;previous=point
            result=original(run,start,joints,points,cfg,speed,progress,**flags)
            other.state['joints']=q
            return result
        drop.exchange.LuaTrajectory.return_value.execute.side_effect=queue
        with patch.object(drop,'FOLDER',Path(other.tmp.name)/'dropoffs'):
            p=drop.exchange.plan(other.svc,other.route['config'],'fake',True)
            r=drop.exchange.execute(other.run,other.svc,other.route['config'],p)
            p=drop.plan(other.svc,other.route['config'],'release',r['record'])
            r=drop.execute(other.run,other.svc,other.route['config'],p)
            self.assertEqual(r['status'],drop.STATUSES['release'])
            self.assertEqual(other.jaws,[26,25,28])

    def test_deliver_stops_held_without_release_or_reverse(self):
        f=self.fixture;r=self.phase('deliver')
        self.assertEqual(r['status'],drop.STATUSES['deliver'])
        self.assertEqual(f.jaws,[26,25])
        self.assertEqual(len(f.moves),4)
        self.assertEqual(f.state['pose_mm'],f.route['routes']['reverse']['start'])
        self.assertEqual(f.rotations,[])

    def test_release_has_no_arm_move_and_return_uses_exact_reverse_without_reseating(self):
        f=self.fixture;delivery=self.phase('deliver');count=len(f.moves)
        release=self.phase('release',delivery['record'])
        self.assertEqual(len(f.moves),count);self.assertEqual(f.jaws[-1],28)
        result=self.phase('return',release['record'])
        self.assertEqual(f.moves[count]['points'],f.route['routes']['reverse']['points'])
        self.assertEqual(f.moves[count]['flags']['segment_speeds'],[5,137,137,137,137])
        self.assertEqual(len(f.moves),count+2)
        self.assertAlmostEqual(result['pose_mm']['Z'],104.37)
        self.assertEqual(f.jaws,[26,25,28])

    def test_timeout_stops_without_retry_release_or_reverse(self):
        f=self.fixture;original=f.queue
        def fail(*args,**kwargs):
            if kwargs.get('hamilton_short_side'):raise TimeoutError('uncertain')
            return original(*args,**kwargs)
        drop.LuaTrajectory.return_value.execute.side_effect=fail
        with self.assertRaises(TimeoutError):self.phase('deliver')
        self.assertEqual(f.jaws[-1],25);self.assertEqual(len(f.moves),3)
        with self.assertRaisesRegex(drop.TransferError,'already attempted'):self.phase('deliver')

    def test_stale_evidence_refused_before_motion(self):
        self.data['finished_at']=time.time()-1801;self.source.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(drop.TransferError,'not fresh'):self.phase('deliver')
        self.assertEqual(self.fixture.moves,[])

    def test_changed_route_refused_before_motion(self):
        self.data['plan']['forward']['points'][-1]['Z']+=1
        self.source.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(drop.TransferError,'route/grip changed'):self.phase('deliver')
        self.assertEqual(self.fixture.moves,[])

    def test_wrong_jaw_position_refused(self):
        self.fixture.state['external_axes']['E1']=25
        with self.assertRaisesRegex(drop.TransferError,'Jaw position'):self.phase('deliver')
        self.assertEqual(self.fixture.moves,[])

    def test_retrieval_seats_held_then_releases_home_separately(self):
        f=self.fixture;r=self.phase('deliver')
        for phase in ('release','return','retrieve'):r=self.phase(phase,r['record'])
        self.assertEqual(r['status'],drop.STATUSES['retrieve'])
        self.assertEqual(f.jaws[-1],25)
        self.assertEqual(f.state['pose_mm'],drop.seating_plan(f.grip['descent_endpoint'])['pose'])
        self.assertEqual(f.moves[-1]['points'],[drop.seating_plan(f.grip['descent_endpoint'])['pose']])
        self.assertEqual(f.moves[-1]['speed'],5)
        before=deepcopy(f.grip['descent_endpoint']);jaw=f.svc.move_gripper.side_effect
        def verify_release(target,speed):
            self.assertEqual(f.state['pose_mm'],dict(before,Z=before['Z']-1))
            self.assertEqual(f.moves[-1]['speed'],5)
            return jaw(target,speed)
        f.svc.move_gripper.side_effect=verify_release
        count=len(f.moves);r=self.phase('finish_home',r['record'])
        self.assertEqual(len(f.moves),count+1) # Only the empty rise; no second downward command.
        self.assertEqual(f.jaws[-1],28);self.assertAlmostEqual(r['pose_mm']['Z'],104.37)
        self.assertEqual(f.grip['descent_endpoint'],before)
        f.svc.move_gripper.side_effect=jaw
        r=self.phase('deliver',r['record'])
        self.assertEqual(r['status'],drop.STATUSES['deliver'])

    def test_failed_lowering_does_not_open_or_rise(self):
        f=self.fixture;r=self.phase('deliver')
        for phase in ('release','return'):r=self.phase(phase,r['record'])
        original=drop.LuaTrajectory.return_value.execute.side_effect
        def fail(run,start,joints,points,*args,**kwargs):
            if points==[drop.seating_plan(f.grip['descent_endpoint'])['pose']]:raise TimeoutError('seating uncertain')
            return original(run,start,joints,points,*args,**kwargs)
        drop.LuaTrajectory.return_value.execute.side_effect=fail
        with self.assertRaisesRegex(TimeoutError,'seating uncertain'):self.phase('retrieve',r['record'])
        self.assertEqual(f.jaws[-2:],[26,25])
        self.assertEqual(f.state['pose_mm'],f.grip['proof_lift_endpoint'])
        self.assertEqual(f.state['external_axes']['E1'],25)

    def test_modified_release_depth_rejected_before_moving(self):
        f=self.fixture;r=self.phase('deliver')
        for phase in ('release','return','retrieve'):r=self.phase(phase,r['record'])
        p=drop.plan(f.svc,f.route['config'],'finish_home',r['record'])
        p['home_seating']['pose']['Z']-=1
        count=len(f.moves)
        with self.assertRaisesRegex(drop.TransferError,'plan changed'):
            drop.execute(f.run,f.svc,f.route['config'],p)
        self.assertEqual(len(f.moves),count)

    def test_old_seating_receipt_cannot_trigger_extra_lowering_or_release(self):
        f=self.fixture;r=self.phase('deliver')
        for phase in ('release','return','retrieve'):r=self.phase(phase,r['record'])
        path=Path(r['record']);data=json.loads(path.read_bytes())
        data['plan']['home_seating'].pop('mode');path.write_text(json.dumps(data))
        count=len(f.moves);jaws=list(f.jaws)
        with self.assertRaisesRegex(drop.TransferError,'fresh retrieval'):self.phase('finish_home',path)
        self.assertEqual(len(f.moves),count);self.assertEqual(f.jaws,jaws)

    def test_holder_changed_during_retrieval_stops_before_seating(self):
        f=self.fixture;r=self.phase('deliver')
        for phase in ('release','return'):r=self.phase(phase,r['record'])
        original=drop.LuaTrajectory.return_value.execute.side_effect
        def changed(*args,**kwargs):
            result=original(*args,**kwargs)
            if kwargs.get('hamilton_short_side')=='pickup_hover04_reverse':f.angle+=1
            return result
        drop.LuaTrajectory.return_value.execute.side_effect=changed
        with self.assertRaisesRegex(drop.TransferError,'Holder changed'):self.phase('retrieve',r['record'])
        self.assertEqual(f.jaws[-1],25)
        self.assertEqual(f.state['pose_mm'],f.grip['proof_lift_endpoint'])


if __name__=='__main__':main()
