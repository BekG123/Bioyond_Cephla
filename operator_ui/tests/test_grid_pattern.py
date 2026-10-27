"""Known image transformations and rejection tests; no robot access."""
import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Pick and Hold/Align/plate_pose'))
from grid_pattern import GridPatternTracker,commissioned_grid_tracker
from project_taught_disks import transform
from vision import DetectionError


class GridPatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
        ref=cv2.imread(r['images']['target']['path'])
        cls.t=GridPatternTracker(ref,r['corners_native_px']['target'],{c['label']:c['pixels'] for c in r['virtual_circles']})
        cls.image=cls.t.gray(cv2.imread(str(ROOT/'operator_ui/reports/projected_disk_pilot/wider_view_validation_20261026/fresh_1.jpg')))
        cls.baseline=np.asarray(cls.t.track(cls.image)['H_preview_from_reference_preview'])
        cls.points=np.vstack(list(cls.t.outlines.values()))
        cls.anchored=commissioned_grid_tracker(ROOT,r,ref)

    def setUp(self):
        self.anchored.previous_verified_seed=None
        self.anchored.template_scale_search=False

    def test_height_scale_search_recovers_known_scale_without_reference_update(self):
        image=self.t.gray(cv2.imread(str(ROOT/'operator_ui/reports/projected_disk_pilot/grid_pattern_after_move_20261026/fresh_1.jpg')))
        self.anchored.template_scale_search=True
        before=self.anchored.track(image)
        for scale in (.90,1.03):
            with self.subTest(scale=scale):
                self.anchored.previous_verified_seed=None
                known=np.array([[scale,0,(1-scale)*600],[0,scale,(1-scale)*400],[0,0,1.]])
                after=self.anchored.track(cv2.warpPerspective(image,known,self.t.size))
                expected=transform(self.points,known@np.array(before['H_preview_from_reference_preview']))
                actual=transform(self.points,after['H_preview_from_reference_preview'])
                self.assertLess(np.linalg.norm(actual-expected,axis=1).max(),.8)
                self.assertEqual(after['reference_updates'],0)

    def test_recovers_known_shifts_perspective_and_brightness(self):
        for known in (np.array([[1.,0,4.],[0,1.,-3.],[0,0,1.]]),
                      np.array([[.995,.008,2.],[-.006,1.002,1.],[.000002,-.000001,1.]])):
            with self.subTest(transform=known.tolist()):
                image=cv2.warpPerspective(self.image,known,self.t.size)
                image=np.clip(image*.85+15,0,255).astype(np.uint8)
                result=self.t.track(image)
                actual=transform(self.points,result['H_preview_from_reference_preview'])
                expected=transform(self.points,known@self.baseline)
                self.assertLess(np.linalg.norm(actual-expected,axis=1).max(),.8)
                self.assertGreaterEqual(result['supported_wells'],40)

    def test_blank_rejected_even_with_correct_seed(self):
        with self.assertRaises(DetectionError):
            self.t.track(np.full_like(self.image,128),seed=self.baseline)

    def test_occluded_grid_rejected_even_with_seed(self):
        image=self.image.copy();image[:,600:]=128
        with self.assertRaises(DetectionError):self.t.track(image,seed=self.baseline)

    def test_large_rotation_rejected(self):
        h=np.array([[-1.,0,1200.],[0,-1.,800.],[0,0,1.]])
        with self.assertRaises(DetectionError):self.t.track(cv2.warpPerspective(self.image,h,self.t.size),seed=h@self.baseline)

    def test_shape_and_clipped_geometry_rejected(self):
        with self.assertRaises(DetectionError):self.t.track(np.zeros((800,800),np.uint8))
        h=np.array([[1.,0,500.],[0,1.,0.],[0,0,1.]])
        with self.assertRaises(DetectionError):self.t.track(self.image,seed=h@self.baseline)

    def test_frozen_anchor_composition_recovers_known_move(self):
        image=self.t.gray(cv2.imread(str(ROOT/'operator_ui/reports/projected_disk_pilot/grid_pattern_after_move_20261026/fresh_1.jpg')))
        before=self.anchored.track(image)
        known=np.array([[1.,0,4.],[0,1.,-3.],[0,0,1.]])
        after=self.anchored.track(cv2.warpPerspective(image,known,self.t.size))
        expected=transform(self.points,known@np.array(before['H_preview_from_reference_preview']))
        actual=transform(self.points,after['H_preview_from_reference_preview'])
        self.assertLess(np.linalg.norm(actual-expected,axis=1).max(),.8)
        self.assertEqual(after['reference_updates'],0)
        self.assertLessEqual(after['disk_group_spread_px'],.8)

    def test_anchor_does_not_accept_missing_plate(self):
        with self.assertRaises(DetectionError):self.anchored.track(np.full_like(self.image,128))

    def test_whole_plate_reacquisition_recovers_move_and_rejects_occlusion(self):
        image=self.t.gray(cv2.imread(str(ROOT/'operator_ui/reports/projected_disk_pilot/grid_pattern_after_move_20261026/fresh_1.jpg')))
        before=self.anchored.track(image)
        self.anchored.previous_verified_seed=None
        known=np.array([[1.,0,12.],[0,1.,-4.],[0,0,1.]])
        shifted=cv2.warpPerspective(image,known,self.t.size)
        after=self.anchored.track(shifted)
        self.assertEqual(after['initialization']['method'],'whole_plate_template')
        actual=transform(self.points,after['H_preview_from_reference_preview'])
        expected=transform(self.points,known@np.array(before['H_preview_from_reference_preview']))
        self.assertLess(np.linalg.norm(actual-expected,axis=1).max(),.8)
        self.anchored.previous_verified_seed=None
        shifted[:,600:]=128
        with self.assertRaises(DetectionError):self.anchored.track(shifted)

    def test_temporal_seed_keeps_frozen_reference_and_rejects_missing_plate(self):
        from copy import copy
        tracker=copy(self.anchored)
        tracker.previous_verified_seed=None
        image=self.t.gray(cv2.imread(str(ROOT/'operator_ui/reports/projected_disk_pilot/grid_pattern_after_move_20261026/fresh_1.jpg')))
        before=tracker.track(image)
        seed=tracker.previous_verified_seed.copy()
        reference_hash=tracker.anchor_hash
        with self.assertRaises(DetectionError):tracker.track(np.full_like(image,128))
        np.testing.assert_array_equal(seed,tracker.previous_verified_seed)
        known=np.array([[1.,0,4.],[0,1.,-3.],[0,0,1.]])
        after=tracker.track(cv2.warpPerspective(image,known,tracker.size))
        expected=transform(self.points,known@np.array(before['H_preview_from_reference_preview']))
        actual=transform(self.points,after['H_preview_from_reference_preview'])
        self.assertLess(np.linalg.norm(actual-expected,axis=1).max(),.8)
        self.assertEqual(after['initialization']['method'],'previous_verified_initialization')
        self.assertEqual(after['anchor_sha256'],reference_hash)
        self.assertEqual(after['reference_updates'],0)

    def test_rotation_initializer_recovers_known_rotation_without_reference_update(self):
        from grid_rotation_seed import rotation_seed
        image=self.anchored.anchor.ref
        h=np.eye(3);h[:2]=cv2.getRotationMatrix2D((600,400),3.25,1.)
        rotated=cv2.warpPerspective(image,h,self.t.size)
        seed,info=rotation_seed(self.anchored,rotated)
        self.assertIsNotNone(seed)
        points=self.anchored.anchor.corners
        self.assertLess(np.linalg.norm(transform(points,seed)-transform(points,h),axis=1).max(),2.)
        self.assertFalse(info['accepted_pose'])
        measured=self.anchored.anchor.track(rotated,seed=seed)
        self.assertLess(np.linalg.norm(transform(points,measured['H_preview_from_reference_preview'])-transform(points,h),axis=1).max(),.8)
        self.assertEqual(measured['reference_updates'],0)

    def test_rotation_initializer_rejects_blank(self):
        from grid_rotation_seed import rotation_seed
        seed,_=rotation_seed(self.anchored,np.full_like(self.image,128))
        self.assertIsNone(seed)

    def test_measured_grid_keeps_priority_over_rotation_fallback(self):
        with patch.object(self.anchored,'template_seed',return_value=(None,None)), \
             patch.object(self.anchored,'texture_seed',return_value=(None,None)), \
             patch.object(self.anchored.anchor,'grid',return_value=self.anchored.anchor.ref_grid), \
             patch('grid_rotation_seed.rotation_seed') as fallback:
            seed,info=self.anchored.initial_seed(self.image)
        fallback.assert_not_called()
        np.testing.assert_allclose(seed,np.eye(3),atol=1e-9)
        self.assertEqual(info['method'],'measured_well_grid')


if __name__=='__main__':unittest.main()
