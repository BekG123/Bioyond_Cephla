import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import projected_disk_trial as trial


class PilotTests(unittest.TestCase):
    def test_height_matched_centering_rejects_wrong_height_before_motion(self):
        self.exercise_height_reference(268.,False)

    def test_height_matched_centering_uses_pinned_reference_and_stationary_checks(self):
        self.exercise_height_reference(289.129,True)

    def exercise_height_reference(self,z,accepted):
        pose=dict(X=280.,Y=29.,Z=z,Rz=-3.88)
        run=SimpleNamespace(target=None,state='running',stopped=lambda:False,say=Mock())
        guard=Mock();guard.pose_mm.return_value=pose
        measured=dict(error_xy_mm=[.2,.1])
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(trial,'ROOT',Path(temp)), \
             patch.object(trial,'GuardedService',return_value=guard), \
             patch('projected_alignment.perception_at_height',return_value=(Mock(),dict(observation_z_mm=289.129),{})), \
             patch.object(trial,'stationary_observation',return_value=(pose,measured)) as observe:
            result=trial.pilot(run,Mock(),Mock(),{},dict(expected_start=pose,tracking_mode='height_referenced_grid',finish_centering=True))
        self.assertEqual(result['ok'],accepted)
        guard.move_cartesian.assert_not_called()
        self.assertEqual(observe.call_count,2 if accepted else 0)
        if accepted:self.assertTrue(result['xy_centered'])
        else:self.assertIn('verified observation height',result['error'])

    def test_reacquires_after_robot_motion_without_reusing_stationary_seed(self):
        p=trial.Perception.__new__(trial.Perception)
        p.native_size=[30,20]
        pose=dict(X=290.,Y=63.,Z=268.,Rz=-4.)
        p.last_measurement_pose=pose
        p.tracker=Mock();p.tracker.track.side_effect=trial.DetectionError('not acquired')
        seed=np.eye(3);p.tracker.previous_verified_seed=seed
        frame=np.zeros((20,30,3),np.uint8)
        with self.assertRaises(trial.DetectionError):p.measure(frame,dict(pose))
        self.assertIs(p.tracker.previous_verified_seed,seed)
        with self.assertRaises(trial.DetectionError):p.measure(frame,dict(pose,Y=61.))
        self.assertIsNone(p.tracker.previous_verified_seed)
        self.assertEqual(p.last_measurement_pose,pose)

    def test_experimental_tracker_requires_explicit_selection(self):
        b=dict(confirm=True,cell_clear=True,empty_gripper=True,expected_start=dict(X=290,Y=63,Z=248,Rz=-4))
        self.assertEqual(trial.validate_request(b)['tracking_mode'],'rim')
        self.assertEqual(trial.validate_request(dict(b,tracking_mode='grid_pattern'))['tracking_mode'],'grid_pattern')
        with self.assertRaises(trial.TransferError):trial.validate_request(dict(b,tracking_mode='guess'))
        with self.assertRaises(trial.TransferError):trial.validate_request(dict(b,scale_search=True))
        with self.assertRaises(trial.TransferError):trial.validate_request(dict(b,tracking_mode='anchored_grid',scale_search='yes'))
        self.assertTrue(trial.validate_request(dict(b,tracking_mode='anchored_grid',scale_search=True))['scale_search'])

    def test_request_requires_explicit_physical_confirmations(self):
        for key in ('confirm','cell_clear','empty_gripper'):
            b=dict(confirm=True,cell_clear=True,empty_gripper=True,expected_start=dict(X=290,Y=63,Z=248,Rz=-4))
            b[key]=False
            with self.assertRaises(trial.TransferError): trial.validate_request(b)

    def test_bounded_xy_only_target(self):
        p=dict(X=290.,Y=63.,Z=248.,Rz=-4.)
        t=trial.pilot_target(p,[-20,30])
        self.assertAlmostEqual(np.hypot(t['X']-p['X'],t['Y']-p['Y']),2.)
        self.assertEqual((t['Z'],t['Rz']),(p['Z'],p['Rz']))
        for e in ([0,0],[100,0],[float('nan'),1]):
            with self.assertRaises(trial.TransferError): trial.pilot_target(p,e)

    def test_fine_centering_shrinks_step_without_overshoot(self):
        p=dict(X=290.,Y=63.,Z=268.02,Rz=-3.88)
        for error in ([.9,0],[1.5,0],[4,3]):
            t=trial.pilot_target(p,error,finish_centering=True)
            distance=np.hypot(t['X']-p['X'],t['Y']-p['Y'])
            self.assertAlmostEqual(distance,min(2,.7*np.linalg.norm(error)))
            self.assertEqual((t['Z'],t['Rz']),(p['Z'],p['Rz']))
        with self.assertRaises(trial.TransferError):trial.pilot_target(p,[.7,0],finish_centering=True)

    def exercise(self,direction=1.,fail_before=False):
        start=dict(X=290.,Y=63.,Z=248.,Rz=-4.);pose=dict(start)
        run=SimpleNamespace(target={'stale':1},state='running',stopped=lambda:False,say=Mock())
        svc=Mock();cam=Mock();cam.snap.return_value=np.zeros((20,30,3),np.uint8)
        guard=Mock();guard.pose_mm.side_effect=lambda:dict(pose)
        guard.path_envelope={};guard.torque_report.return_value=dict(e1_position=3.7,e1_torque=0.)
        def move(x,y,z,rz,*args): pose.update(X=x,Y=y,Z=z,Rz=rz)
        guard.move_cartesian.side_effect=move
        perception=Mock();perception.burst_frames=1
        def measure(frame,p):
            if fail_before: raise trial.TransferError('Tracking lost')
            delta=np.array([p['X']-start['X'],p['Y']-start['Y']])
            return dict(error_xy_mm=(np.array([20.,10.])-direction*delta).tolist())
        perception.measure.side_effect=measure
        with tempfile.TemporaryDirectory() as temp,patch.object(trial,'ROOT',Path(temp)),patch.object(trial,'GuardedService',return_value=guard),patch.object(trial,'check_path'):
            result=trial.pilot(run,svc,cam,{},dict(expected_start=start),perception)
        self.assertIsNone(run.target)
        self.assertFalse(result['grasp_target_created'])
        self.assertFalse(result['calibration_complete'])
        self.assertEqual(guard.move_cartesian.call_count,0 if fail_before else 1)
        svc.move_gripper.assert_not_called()
        return result

    def test_pilot_validates_observed_response_then_stops(self):
        self.assertTrue(self.exercise()['pilot_verified'])

    def test_wrong_response_stops_without_retry(self):
        result=self.exercise(direction=-1)
        self.assertFalse(result['ok'])
        self.assertIn('disagrees',result['error'])

    def test_lost_vision_starts_no_move(self):
        self.assertFalse(self.exercise(fail_before=True)['motion_requested'])

    def test_burst_rejects_arm_motion_before_measurement(self):
        p=dict(X=290.,Y=63.,Z=268.02,Rz=-3.88)
        guard=Mock();guard.pose_mm.side_effect=[p,p,dict(p,X=291.)]
        cam=Mock();cam.snap.return_value=np.zeros((20,30,3),np.uint8)
        perception=Mock();perception.burst_frames=5
        with self.assertRaises(trial.TransferError):trial.observe(guard,cam,perception,Mock())
        perception.measure.assert_not_called()

    def test_burst_rejects_repeated_stale_frames(self):
        guard=Mock();guard.pose_mm.return_value=dict(X=290.,Y=63.,Z=268.02,Rz=-3.88)
        cam=Mock();cam.snap.return_value=np.zeros((20,30,3),np.uint8)
        perception=Mock();perception.burst_frames=5
        with self.assertRaises(trial.DetectionError):trial.observe(guard,cam,perception,Mock())
        perception.measure.assert_not_called()

    def test_centered_check_never_moves_and_requires_repeat_agreement(self):
        p=dict(X=290.,Y=63.,Z=268.02,Rz=-3.88)
        for errors,success in (([[.3,.1],[.35,.1]],True),([[.3,.1],[.7,.1]],False)):
            guard=Mock();guard.pose_mm.return_value=p
            run=SimpleNamespace(target={},state='running',stopped=lambda:False,say=Mock())
            with tempfile.TemporaryDirectory() as temp,patch.object(trial,'ROOT',Path(temp)),patch.object(trial,'GuardedService',return_value=guard),patch.object(trial,'stationary_observation',side_effect=[(p,dict(error_xy_mm=e)) for e in errors]):
                result=trial.pilot(run,Mock(),Mock(),{},dict(expected_start=p,finish_centering=True),Mock())
            self.assertEqual(result['ok'],success)
            if success:self.assertTrue(result['xy_centered'])
            guard.move_cartesian.assert_not_called()

    def test_stationary_rejection_resets_consecutive_count(self):
        pose=dict(X=290.,Y=63.,Z=248.,Rz=-4.)
        guard=Mock();guard.pose_mm.return_value=pose
        observation=(pose,dict(error_xy_mm=[10.,20.]))
        record=Mock()
        with patch.object(trial,'observe',side_effect=[observation,trial.DetectionError('lost'),observation,observation,observation]) as observed,patch.object(trial.time,'sleep'):
            trial.stationary_observation(guard,Mock(),Mock(),record)
        self.assertEqual(observed.call_count,5)
        record.assert_called_once()
        guard.move_cartesian.assert_not_called()

    def test_stationary_vision_deadline_and_fault_do_not_move(self):
        pose=dict(X=290.,Y=63.,Z=248.,Rz=-4.)
        guard=Mock();guard.pose_mm.return_value=pose
        with patch.object(trial,'observe',side_effect=trial.DetectionError('lost')),patch.object(trial.time,'monotonic',side_effect=[0.,1.,21.]),patch.object(trial.time,'sleep'):
            with self.assertRaisesRegex(trial.TransferError,'No three consecutive'):trial.stationary_observation(guard,Mock(),Mock(),Mock())
        with patch.object(trial,'observe',side_effect=trial.TransferError('controller fault')) as observed:
            with self.assertRaisesRegex(trial.TransferError,'controller fault'):trial.stationary_observation(guard,Mock(),Mock(),Mock())
            self.assertEqual(observed.call_count,1)
        guard.move_cartesian.assert_not_called()

    def test_stationary_disagreement_is_not_retried(self):
        pose=dict(X=290.,Y=63.,Z=248.,Rz=-4.)
        guard=Mock();guard.pose_mm.return_value=pose
        with patch.object(trial,'observe',side_effect=[(pose,dict(error_xy_mm=[10.,20.])),(pose,dict(error_xy_mm=[11.,20.]))]) as observed:
            with self.assertRaisesRegex(trial.TransferError,'readings disagree'):trial.stationary_observation(guard,Mock(),Mock(),Mock())
            self.assertEqual(observed.call_count,2)


if __name__=='__main__': unittest.main(verbosity=2)
