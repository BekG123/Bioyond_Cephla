"""Alignment geometry and stop behavior, without hardware access."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import projected_alignment as a
from project_taught_disks import transform
from vision import DetectionError


class HeightReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p,cls.reference,cls.provenance=a.perception_at_height()
        cls.image=cv2.imread(str(a.ROOT/'operator_ui/captures/snap_0014.png'))
        cls.pose=dict(X=279.215,Y=27.604,Z=289.129,Rz=-3.889)

    def setUp(self):
        self.p.tracker.previous_verified_seed=None
        self.p.last_measurement_pose=None

    def test_height_anchor_retains_all_upstream_fits_and_known_motion(self):
        t=self.p.tracker
        self.assertEqual(len(t.registration['group_homographies']),4)
        before=t.track(self.image)
        known=np.array([[1.,0,4.],[0,1.,-3.],[0,0,1.]])
        t.previous_verified_seed=None
        after=t.track(cv2.warpPerspective(t.anchor.gray(self.image),known,t.size))
        points=np.vstack(list(t.original.outlines.values()))
        expected=transform(points,known@np.asarray(before['H_preview_from_reference_preview']))
        actual=transform(points,after['H_preview_from_reference_preview'])
        self.assertLess(np.linalg.norm(actual-expected,axis=1).max(),.8)
        self.assertEqual(after['reference_updates'],0)

    def test_occluded_plate_rejected(self):
        image=self.image.copy();image[:,image.shape[1]//2:]=128
        with self.assertRaises(DetectionError):self.p.tracker.track(image)

    def test_upstream_uncertainty_cannot_be_reset(self):
        t=self.p.tracker
        saved=t.registration['group_homographies']
        altered=np.asarray(saved).copy();altered[0,0,2]+=3
        try:
            t.registration['group_homographies']=altered.tolist()
            with self.assertRaisesRegex(DetectionError,'Composed grid groups disagree'):
                t.track(self.image)
        finally:t.registration['group_homographies']=saved

    def test_xy_yaw_matches_vendor_composition_without_radius_depth(self):
        m=self.p.measure(self.image,self.pose)
        actual=a.target_from_mark(self.pose,m,self.p.cfg)
        cur=[self.pose[k] for k in ('X','Y','Z')]+[0,0,self.pose['Rz']]
        cfg=self.p.cfg
        off=a.teach.tool_offset_xyrz(cfg,a.teach.mark_in_robot_pose(cfg,m['mark']))
        expected=a.teach.final_acc_pose(cfg,a.teach.new_acc_pose(cur,off))
        np.testing.assert_allclose([actual['x'],actual['y'],actual['rz']],
                                   [expected[0],expected[1],a.wrap(expected[5])])
        self.assertNotIn('z_calibrated',actual)


class ExecutionTests(unittest.TestCase):
    def exercise(self,changed=False,vision_failed=False,executor_failed=False):
        pose=dict(X=279.215,Y=27.604,Z=289.129,Rz=-3.889)
        target=dict(x=300.,y=-70.,rz=90.)
        config=dict(expected_start=pose,expected_target=dict(target,x=310.) if changed else target)
        guard=Mock();guard.pose_mm.return_value=pose
        guard.torque_report.return_value=dict(e1_position=.02,e1_torque=-1)
        p=Mock();p.cfg={}
        run=SimpleNamespace(target={'old':True},say=Mock(),state='running',stopped=lambda:False)
        svc=Mock();svc.envelope={}
        route=dict(target=target,hover_z=300.,waypoints=[])
        measurement=dict(mark=[1,2,3])
        with tempfile.TemporaryDirectory() as folder,patch.object(a,'ROOT',Path(folder)),\
                patch.object(a,'GuardedService',return_value=guard),\
                patch.object(a,'perception_at_height',return_value=(p,dict(observation_z_mm=pose['Z']),{})),\
                patch.object(a,'stationary_observation',return_value=(pose,measurement)) as observe,\
                patch.object(a,'target_from_mark',return_value=target),\
                patch.object(a,'plan',return_value=route),\
                patch('sequences.seq_align',return_value=dict(ok=not executor_failed,error='test failure')) as executor:
            if vision_failed:observe.side_effect=DetectionError('plate not found')
            result=a.align(run,svc,Mock(),{},config)
            self.assertEqual(executor.call_count,0 if changed or vision_failed else 1)
            if executor.called:self.assertFalse(executor.call_args.kwargs['validate_descent'])
            self.assertIsNone(run.target)
            svc.move_gripper.assert_not_called()
            return result

    def test_alignment_only_never_publishes_grasp(self):
        r=self.exercise()
        self.assertTrue(r['ok']);self.assertTrue(r['visual_acceptance_pending'])
        self.assertFalse(r['grasp_target_created']);self.assertFalse(r['descent_executed'])

    def test_changed_target_stops_before_motion(self):self.assertFalse(self.exercise(changed=True)['ok'])
    def test_lost_vision_stops_before_motion(self):self.assertFalse(self.exercise(vision_failed=True)['ok'])
    def test_executor_failure_is_not_retried(self):self.assertFalse(self.exercise(executor_failed=True)['ok'])

    def test_requires_start_target_and_physical_confirmations(self):
        body=dict(confirm=True,cell_clear=True,empty_gripper=True,
                  expected_start=dict(X=279.,Y=27.,Z=289.,Rz=-4.),
                  expected_target=dict(x=300.,y=-70.,rz=90.))
        self.assertIn('expected_target',a.validate_request(body))
        for key in ('confirm','cell_clear','empty_gripper','expected_target','expected_start'):
            altered=dict(body);del altered[key]
            with self.assertRaises(a.TransferError):a.validate_request(altered)


if __name__=='__main__':unittest.main()
