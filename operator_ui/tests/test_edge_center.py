"""Edge centering tests with synthetic images/robot responses; no hardware."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from test_transfer import FakeService, PARAMS
from sequences import Runner
from edge_center import (center, preview, CameraMapping, validate_request,
                         verify_response, TransferError)

BODY=dict(confirm=True,cell_clear=True,empty_gripper=True,outline_verified=True,camera_distance_mm=205)


class LinearMapping:
    stamp='test-calibration'
    def correction(self,d,rz,gap):
        return np.asarray(d['offset_px'])*.1


class EdgeCenterTests(unittest.TestCase):
    def setUp(self):
        self.svc,self.run=FakeService(),Runner()
        self.run.state='running'
        self.goal=np.array([346.,0.])
        self.calls=0
        self.missing=False
        self.reverse=False
        self.initial_pose=np.array([326.,0.])
        self.cam=SimpleNamespace(snap=lambda:np.zeros((800,1000,3),np.uint8))

    def detection(self,frame):
        self.calls+=1
        if self.missing:
            return dict(detected=False,reason='outline missing'),None
        position=np.array([self.svc.pose['X'],self.svc.pose['Y']])
        if self.reverse:
            position=2*self.initial_pose-position
        offset=(self.goal-position)/.1
        c=np.array([499.5,399.5])+offset
        corners=np.array([[-150,-100],[150,-100],[150,100],[-150,100]])+c
        return dict(detected=True,candidate_count=1,image_size=[1000,800],center_px=c.tolist(),
                    image_center_px=[499.5,399.5],offset_px=offset.tolist(),corners=corners.tolist(),
                    side_support=[1.]*4,angle_image_deg=7.5),None

    def execute(self,detector=None):
        with patch('edge_center.detect_plate',side_effect=detector or self.detection), \
             patch('edge_center.save_overlay',return_value='fake_overlay.jpg'):
            return center(self.run,self.svc,self.cam,PARAMS,validate_request(BODY),LinearMapping())

    def test_success_first_pilot_fixed_z_yaw_no_target(self):
        self.run.target={'old':True}
        result=self.execute()
        self.assertTrue(result['ok'],result)
        self.assertTrue(result['centered'])
        self.assertFalse(result['grasp_target_created'])
        self.assertIsNone(self.run.target)
        self.assertEqual(self.svc.moves[0],(328.,0.,300.,0.))
        self.assertTrue(all(m[2:]==(300.,0.) for m in self.svc.moves))
        self.assertEqual(self.svc.grips,[])
        self.assertGreaterEqual(result['views'],result['moves']+3)

    def test_already_centered_two_images_no_motion(self):
        self.goal=self.initial_pose.copy()
        result=self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['views'],2)
        self.assertEqual(self.svc.moves,[])

    def test_first_image_is_stationary_confirmed_before_pilot(self):
        move=self.svc.move_cartesian
        def observed_move(*args):
            self.assertGreaterEqual(self.calls,2)
            return move(*args)
        self.svc.move_cartesian=observed_move
        self.assertTrue(self.execute()['ok'])

    def test_wrong_mapping_stops_after_pilot(self):
        self.reverse=True
        result=self.execute()
        self.assertFalse(result['ok'])
        self.assertIn('image response',result['error'])
        self.assertEqual(len(self.svc.moves),1)

    def test_missing_outline_no_search(self):
        self.missing=True
        result=self.execute()
        self.assertFalse(result['ok'])
        self.assertEqual(self.svc.moves,[])

    def test_lost_after_move_no_retry(self):
        def detect(frame):
            if self.svc.moves:
                self.missing=True
            return self.detection(frame)
        result=self.execute(detect)
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.svc.moves),1)

    def test_ambiguous_outline_no_motion(self):
        def detect(frame):
            d,e=self.detection(frame)
            d['candidate_count']=2
            return d,e
        self.assertFalse(self.execute(detect)['ok'])
        self.assertEqual(self.svc.moves,[])

    def test_stationary_jitter_no_motion(self):
        def detect(frame):
            if self.calls:
                self.goal+=np.array([2.,0.])
            return self.detection(frame)
        self.assertFalse(self.execute(detect)['ok'])
        self.assertEqual(self.svc.moves,[])

    def test_target_outside_envelope_no_partial_motion(self):
        self.svc.envelope['X']=(320,335)
        result=self.execute()
        self.assertFalse(result['ok'])
        self.assertIn('envelope',result['error'])
        self.assertEqual(self.svc.moves,[])

    def test_missing_telemetry_holding_and_missing_joints(self):
        for fault in ('telemetry','holding','joints','envelope'):
            with self.subTest(fault=fault):
                self.setUp()
                if fault=='telemetry':
                    self.svc.torque_report=lambda:dict(ok=True,telemetry_live=False)
                elif fault=='holding':
                    self.svc.torque=-187
                elif fault=='joints':
                    self.svc.q={}
                else:
                    self.svc.envelope_enabled=False
                self.assertFalse(self.execute()['ok'])
                self.assertEqual(self.svc.moves,[])

    def test_stale_and_recovered_ack_no_retry(self):
        for failure in ('stale','recovered'):
            with self.subTest(failure=failure):
                self.setUp()
                self.svc.motion_failure=failure
                self.assertFalse(self.execute()['ok'])
                self.assertEqual(len(self.svc.moves),1)

    def test_z_drift_stops_before_next_move(self):
        move=self.svc.move_cartesian
        def drift(*args):
            result=move(*args)
            self.svc.pose['Z']+=.2
            return result
        self.svc.move_cartesian=drift
        result=self.execute()
        self.assertFalse(result['ok'])
        self.assertIn('Z or wrist',result['error'])
        self.assertEqual(len(self.svc.moves),1)

    def test_stop_after_pilot(self):
        move=self.svc.move_cartesian
        def stop(*args):
            result=move(*args)
            self.run.request_stop()
            return result
        self.svc.move_cartesian=stop
        result=self.execute()
        self.assertFalse(result['ok'])
        self.assertEqual(self.run.state,'stopped')
        self.assertEqual(len(self.svc.moves),1)

    def test_budgets(self):
        for constant,value in [('MAX_VIEWS',2),('MAX_SECONDS',-1),('MAX_TRAVEL_MM',1)]:
            with self.subTest(constant=constant):
                self.setUp()
                with patch('edge_center.'+constant,value):
                    self.assertFalse(self.execute()['ok'])
                self.assertIsNone(self.run.target)

    def test_preview_no_robot_and_preserves_target(self):
        self.run.target={'existing':True}
        with patch('edge_center.detect_plate',side_effect=self.detection), \
             patch('edge_center.save_overlay',return_value='fake.jpg'):
            result=preview(self.run,self.cam)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.run.target,{'existing':True})
        self.assertEqual(self.svc.moves,[])

    def test_flask_routes_and_confirmation(self):
        import app as console
        with patch.object(console.runner,'start',return_value=dict(ok=True)) as start:
            client=console.app.test_client()
            self.assertEqual(client.post('/seq/center_plate_edges',json={}).status_code,400)
            self.assertEqual(client.post('/seq/center_plate_edges',json={**BODY,'outline_verified':False}).status_code,400)
            start.assert_not_called()
            self.assertEqual(client.post('/seq/center_plate_edges',json=BODY).status_code,200)
            self.assertIs(start.call_args.args[1],center)
            self.assertEqual(client.post('/seq/preview_plate_edges',json={}).status_code,200)
            self.assertIs(start.call_args.args[1],preview)

    def test_gap_and_confirmation_validation(self):
        for gap in (None,True,0,204,241,float('nan')):
            with self.assertRaises(TransferError):
                validate_request({**BODY,'camera_distance_mm':gap})
        for key in ('confirm','cell_clear','empty_gripper','outline_verified'):
            with self.assertRaises(TransferError):
                validate_request({**BODY,key:'true'})

    def test_direction_guard(self):
        with self.assertRaises(TransferError):
            verify_response([10,0],[12,0],[2,0])
        verify_response([10,0],[8,0],[2,0])


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.m=CameraMapping.__new__(CameraMapping)
        self.m.K=np.array([[1000.,0,500],[0,1000,400],[0,0,1]])
        self.m.dist=np.zeros(5)
        self.m.size=[1000,800]
        self.m.scale=1.
        self.m.mirror=-1
        self.m.yaw=90.
        self.d=dict(image_size=[1000,800],center_px=[600.,450.],image_center_px=[500.,400.])
    def test_camera_mirror_and_wrist_rotation(self):
        np.testing.assert_allclose(self.m.correction(self.d,0,205),[10.25,20.5],atol=1e-6)
        np.testing.assert_allclose(self.m.correction(self.d,90,205),[-20.5,10.25],atol=1e-6)
    def test_zero_error(self):
        self.d['center_px']=[500,400]
        np.testing.assert_allclose(self.m.correction(self.d,42,205),[0,0],atol=1e-6)
    def test_wrong_resolution(self):
        self.d['image_size']=[500,400]
        with self.assertRaises(TransferError):
            self.m.correction(self.d,0,205)
    def test_real_calibration_can_load_without_hardware(self):
        m=CameraMapping()
        self.assertEqual(m.size,[3072,2048])
        self.assertTrue(m.stamp)


if __name__=='__main__':
    unittest.main()
