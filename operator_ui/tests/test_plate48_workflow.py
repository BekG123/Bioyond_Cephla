"""Fake-device integration and unchanged real route/evidence preflight. No network."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plate48_workflow as w
from sequences import Runner
from autonomy import check_path, TransferError
from researcher_descent import ResearcherDescent
from researcher_teaching import TeachingError
import test_pickup_home as home_tests


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.profile,self.digest,self.raw=w.reference()
        self.cfg=json.loads((w.pickup.ROOT/'operator_ui/robot_params.json').read_bytes())
        self.pose=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
        self.homepose=deepcopy(self.pose)
        self.q=dict(J1=209.421,J2=84.877,J3=52.056,J4=-140.813)
        self.moves=[]
        self.env=dict(X=[200,450],Y=[-250,380],Z=[70,400])
        self.service=SimpleNamespace(pose_mm=lambda:deepcopy(self.pose),joints=lambda:deepcopy(self.q),
            envelope=self.env,envelope_enabled=True,_preflight=lambda:None,
            status=lambda:dict(connected=True,ok=True,errors=[]),move_cartesian=self.move)
        self.run=Runner()
        self.camera=SimpleNamespace(info=lambda:dict(enabled=True),snap=lambda:None)
        self.prepare=Mock()
        self.flow=w.Plate48Teaching(lambda:self.service,lambda:self.run,lambda:self.camera,
            lambda:self.cfg,self.prepare,SimpleNamespace(target=lambda:(self.homepose,'home')),Mock(),lambda:66)
        p=SimpleNamespace(cfg={})
        patches=[patch('projected_alignment.perception_at_height',return_value=(p,dict(observation_z_mm=289.129),{})),
                 patch('projected_disk_trial.stationary_observation',side_effect=lambda *args:(deepcopy(self.pose),dict(error_xy_mm=[.1,.1]))),
                 patch('projected_alignment.target_from_mark',side_effect=lambda *args:deepcopy(self.raw))]
        for item in patches:item.start();self.addCleanup(item.stop)

    def move(self,x,y,z,rz,speed,interpolation):
        target=dict(X=x,Y=y,Z=z,Rz=rz)
        self.q=check_path(self.pose,target,self.q,self.cfg,self.env)
        self.pose=target;self.moves.append((target,speed))
        return dict(ok=True)

    def calibrate(self):
        started=self.flow.start('Calibrate',dict(ready=True))
        self.assertTrue(started['ok'])
        self.run._thread.join(5)
        self.assertFalse(self.run.active)
        return self.run.result

    def test_accepted_48well_calibration_uses_reviewed_observation_route(self):
        result=self.calibrate()
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.run.name,'plate48_calibrate')
        self.assertEqual([p['Z'] for p,s in self.moves],[289.129,289.129])
        self.assertEqual([s for p,s in self.moves],[5,5])
        self.assertIsNone(self.run.target)  # No fabricated descent receipt.
        self.assertEqual(self.flow.context['profile_sha256'],self.digest)

    def test_changed_plate_stops_without_align_or_grip(self):
        self.raw['x']+=1
        result=self.calibrate()
        self.assertFalse(result['ok']);self.assertIn('placement changed',result['error'])
        self.assertIsNone(self.flow.context)
        self.assertEqual(len(self.moves),2)

    def test_missing_grid_stops_at_observation_position(self):
        with patch('projected_disk_trial.stationary_observation',side_effect=TransferError('48 wells not detected')):
            result=self.calibrate()
        self.assertFalse(result['ok']);self.assertIsNone(self.flow.context)
        self.assertEqual(len(self.moves),2)

    def test_wrong_start_or_fault_never_prepares_or_moves(self):
        self.pose['X']+=10
        with self.assertRaises(TransferError):self.flow.start('Calibrate',dict(ready=True))
        self.pose=deepcopy(self.homepose)
        self.service.status=lambda:dict(connected=True,ok=True,errors=['fault'])
        with self.assertRaises(TeachingError):self.flow.start('Calibrate',dict(ready=True))
        self.prepare.assert_not_called();self.assertEqual(self.moves,[])

    def test_stop_before_observation_never_moves(self):
        self.prepare.side_effect=lambda *args:self.run.request_stop()
        result=self.calibrate()
        self.assertFalse(result['ok']);self.assertEqual(self.moves,[])

    def test_alignment_reuses_accepted_absolute_hover(self):
        self.assertTrue(self.calibrate()['ok'])
        def raw_align(run,svc,cam,cfg,config):
            from autonomy import alignment_plan
            points=alignment_plan(self.pose,dict(self.raw,z_calibrated=280),self.q,self.cfg,self.env,300,False)
            for p in points:self.move(p['X'],p['Y'],p['Z'],p['Rz'],5,'linear')
            return dict(ok=True,route=dict(target=self.raw))
        with patch('projected_alignment.align',side_effect=raw_align):
            self.flow.start('Align',dict(ready=True));self.run._thread.join(5)
        self.assertTrue(self.run.result['ok'],self.run.result)
        self.assertEqual(self.run.name,'projected_alignment')
        for k in ('X','Y','Z','Rz'):self.assertAlmostEqual(self.pose[k],self.profile['alignment_pose_mm'][k])
        self.assertIsNone(self.flow.context)
        self.assertEqual(self.run.target['plate_profile_id'],w.pickup.PLATE_ID)

    def test_expired_or_changed_profile_blocks_alignment(self):
        self.assertTrue(self.calibrate()['ok'])
        self.flow.context['at']=time.time()-601
        with self.assertRaises(TeachingError):self.flow.start('Align',dict(ready=True))
        self.flow.context['at']=time.time();self.flow.context['profile_sha256']='changed'
        with self.assertRaises(TeachingError):self.flow.start('Align',dict(ready=True))

    def test_profile_change_after_alignment_blocks_descent(self):
        run=SimpleNamespace(name='projected_alignment',result=dict(profile_sha256='old'))
        descent=object.__new__(ResearcherDescent)
        with self.assertRaises(TransferError):descent._target(run)

    def test_intervening_sequence_invalidates_calibration(self):
        self.assertTrue(self.calibrate()['ok'])
        self.run.start('another_sequence',lambda run:dict(ok=True))
        self.run._thread.join(5)
        with self.assertRaises(TeachingError):self.flow.start('Align',dict(ready=True))

    def test_nonfinite_placement_is_rejected(self):
        for key in ('x','y','rz'):
            with self.assertRaises(TransferError):w.match_placement(dict(self.raw,**{key:float('nan')}),self.raw)

    def test_48well_labels_and_requirements(self):
        chain=w.Plate48Pickup(None,None,None,None,None,None)
        self.assertIn('48-well',chain.labels()[0])
        self.assertIn('3.9', ' '.join(chain.requirements))


class Plate48ChainTests(unittest.TestCase):
    def test_all_stages_and_failure_boundaries(self):
        import test_lacry_pickup as chain_tests
        for failure in (None,'Calibrate','Align','Descend','Grip','Lift'):
            with self.subTest(failure=failure):
                fixture=chain_tests.PickupTests()
                fixture.setUp()
                try:
                    fixture.enable_transport()
                    old=fixture.pickup
                    def start(action,body):
                        fixture.calls.append(action)
                        job=dict(Calibrate='plate48_calibrate',Align='projected_alignment')[action]
                        return fixture.run.start(job,lambda run:dict(ok=action!=fixture.fail,error='test failure'))
                    fixture.pickup=w.Plate48Pickup(old.teaching,SimpleNamespace(start=start),old.descent,old.grip,
                                                  old.get_service,old.get_runner,transport=old.transport)
                    fixture.fail=failure
                    fixture.pickup.start()
                    result=fixture.finish()
                    stages=['Calibrate','Align','Descend','Grip','Lift','Home']
                    expected=stages if failure is None else stages[:stages.index(failure)+1]
                    self.assertEqual(fixture.calls,expected)
                    self.assertEqual(result['ok'],failure is None)
                finally:fixture.doCleanups()


class Plate48TransportTests(home_tests.PickupHomeTests):
    def setUp(self):
        super().setUp()
        self.transport.plate_profile=True;self.transport.grip_mm=3.9
        self.service.e1=3.9
        self.grip_result['target_e1_mm']=3.9
        data=json.loads(self.grip.read_text());data['target_e1_mm']=3.9
        self.grip.write_text(json.dumps(data))

    def test_exact_five_mm_slow_lift_then_existing_home_connection(self):
        result=self.lift()
        self.assertTrue(result['ok'],result)
        self.connection.start.return_value=({'ok':True},'home-attempt.json')
        self.transport.start_home(result)
        self.assertEqual(self.connection.start.call_args.args[0]['e1'],3.9)
        self.assertEqual(self.calls[0][1],5)
        self.assertAlmostEqual(self.calls[0][0][0]['Z'],78.72)


if __name__=='__main__':unittest.main()
