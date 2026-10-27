"""Independent geometry and saved-frame tests for the opt-in rim tracker."""
import json
from pathlib import Path
import unittest
import cv2
import numpy as np
from live_projection import Tracker
from project_taught_disks import transform
from vision import DetectionError


class RimTests(unittest.TestCase):
    def fixture(self,seed=31):
        rng=np.random.default_rng(seed)
        image=np.full((800,1200,3),160,np.uint8)
        for side in range(4):
            for i in range(100):
                if side<2:x,y=int(rng.integers(145,1055)),(110 if side==0 else 690)
                else:x,y=(110 if side==2 else 1090),int(rng.integers(145,655))
                radius=int(rng.integers(2,8));value=int(rng.integers(10,245))
                y+=int(rng.integers(-9,10));x+=int(rng.integers(-9,10))
                cv2.circle(image,(x,y),radius,(value,)*3,-1)
        corners=np.float32([[80,80],[1120,80],[1120,720],[80,720]])
        contours={'large':[[360,350],[400,310],[440,350],[400,390]],'small':[[730,350],[750,330],[770,350],[750,370]]}
        return image,corners,contours

    def test_known_motion_with_independently_changing_plate_interior(self):
        image,q,outlines=self.fixture()
        tracker=Tracker(image,q,outlines,mode='rim')
        h=np.array([[.98,.01,26],[-.01,.99,16],[.000005,.000006,1.]])
        moved=cv2.warpPerspective(image,h,(1200,800),borderValue=(160,)*3)
        moved[200:600,200:1000]=np.random.default_rng(6).integers(0,255,(400,800,3),dtype=np.uint8)
        result=tracker.track(moved)
        np.testing.assert_allclose(result['corners_px'],transform(q,h),atol=1.)
        self.assertGreaterEqual(result['inlier_fraction'],.65)
        self.assertLessEqual(result['registration_rmse_px'],.8)
        self.assertEqual(result['matches']*result['inlier_fraction'],result['inliers'])
        self.assertFalse(result['motion_authorized'])

    def test_blank_unrelated_and_clipped_plate_reject(self):
        image,q,outlines=self.fixture();tracker=Tracker(image,q,outlines,mode='rim')
        for other in (np.zeros_like(image),self.fixture(99)[0],cv2.warpAffine(image,np.float32([[1,0,200],[0,1,0]]),(1200,800))):
            with self.assertRaises(DetectionError):tracker.track(other)

    def test_five_real_stationary_validation_frames(self):
        root=Path(__file__).resolve().parents[3]
        ref=root/'operator_ui/reports/plate_projection_taught_48/result.json'
        folder=root/'operator_ui/reports/projected_disk_pilot/strict_matches_validation'
        if not ref.exists() or not (folder/'validation_5.jpg').exists():self.skipTest('Optional camera evidence absent')
        report=json.loads(ref.read_text());image=cv2.imread(report['images']['target']['path'])
        tracker=Tracker(image,report['corners_native_px']['target'],{c['label']:c['pixels'] for c in report['virtual_circles']},mode='rim')
        for n in range(1,6):
            with self.subTest(frame=n):
                result=tracker.track(cv2.imread(str(folder/f'validation_{n}.jpg')))
                self.assertGreaterEqual(result['inlier_fraction'],.65)
                self.assertGreater(result['coverage_fraction'],.85)
                self.assertLessEqual(result['registration_rmse_px'],.8)
                self.assertFalse(result['metric_pose_estimated'])

    def test_saved_failure_pose_and_heldout_frames(self):
        root=Path(__file__).resolve().parents[3]
        folder=root/'operator_ui/reports/projected_disk_pilot/rim_refinement_20261026'
        if not (folder/'validation_5.jpg').exists():self.skipTest('Optional camera evidence absent')
        report=json.loads((root/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
        tracker=Tracker(cv2.imread(report['images']['target']['path']),report['corners_native_px']['target'],
                        {c['label']:c['pixels'] for c in report['virtual_circles']},mode='rim')
        # Only frame1 was used to choose the refinement change; 2..5 are held out.
        for n in range(1,6):
            with self.subTest(frame=n):
                result=tracker.track(cv2.imread(str(folder/f'validation_{n}.jpg')))
                self.assertGreaterEqual(result['inlier_fraction'],.65)
                self.assertLessEqual(result['registration_rmse_px'],.8)
                self.assertAlmostEqual(result['matches']*result['inlier_fraction'],result['inliers'])
                self.assertFalse(result['motion_authorized'])

    def test_reference_does_not_drift_across_known_motion_and_return(self):
        image,q,outlines=self.fixture();tracker=Tracker(image,q,outlines,mode='rim')
        for dx,dy in ((-20,15),(25,-15),(0,0)):
            h=np.array([[1.,.005,dx],[-.005,1.,dy],[0,0,1.]])
            moved=cv2.warpPerspective(image,h,(1200,800),borderValue=(160,)*3)
            result=tracker.track(moved)
            np.testing.assert_allclose(result['corners_px'],transform(q,h),atol=1.)

    def test_rotated_patches_and_second_failure_view(self):
        image,q,outlines=self.fixture();tracker=Tracker(image,q,outlines,mode='rim')
        h=np.vstack([cv2.getRotationMatrix2D((600,400),4.,1.),[0.,0.,1.]])
        moved=cv2.warpPerspective(image,h,(1200,800),borderValue=(160,)*3)
        result=tracker.track(moved)
        np.testing.assert_allclose(result['corners_px'],transform(q,h),atol=1.)
        root=Path(__file__).resolve().parents[3]
        frame=root/'operator_ui/reports/projected_disk_pilot/after_rim_fix_20261026/raw.jpg'
        if frame.exists():
            report=json.loads((root/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
            real=Tracker(cv2.imread(report['images']['target']['path']),report['corners_native_px']['target'],
                         {c['label']:c['pixels'] for c in report['virtual_circles']},mode='rim')
            result=real.track(cv2.imread(str(frame)))
            self.assertGreaterEqual(result['inlier_fraction'],.65)
            self.assertLessEqual(result['registration_rmse_px'],.8)


if __name__=='__main__':unittest.main(verbosity=2)
