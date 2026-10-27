"""48-well and dimensionless image-grid regressions. No hardware access."""
import unittest
from pathlib import Path
import cv2
import numpy as np
from demo import fixtures,render
from vision import analyze,DetectionError
from grid_preview import fit_grid,preview
from alignment_preview import preview as alignment_preview


class Plate48Tests(unittest.TestCase):
    def test_48_metric_synthetic_pose_recovers_render_truth(self):
        model,camera=fixtures(48)
        for angles in ((14,-18,8),(-22,20,-24),(19,12,155)):
            image,truth=render(model,camera,angles,noise=2)
            result,_=analyze(image,model,camera)
            self.assertEqual(result['pose']['matched_wells'],48)
            transform=np.asarray(result['pose']['T_camera_plate'])
            self.assertLess(np.linalg.norm(transform[:3,3]-truth[:3,3]),.3)
            angle=np.degrees(np.arccos(np.clip((np.trace(transform[:3,:3].T@truth[:3,:3])-1)/2,-1,1)))
            self.assertLess(angle,.2)
            self.assertFalse(result['motion_authorized'])

    def test_48_missing_wells_and_unknown_orientation_rejected(self):
        model,camera=fixtures(48)
        for changes in (dict(missing=12),dict(chamfer=False)):
            image,_=render(model,camera,**changes)
            with self.assertRaises(DetectionError):analyze(image,model,camera)

    def test_48_image_is_not_96_metric_model(self):
        m48,camera=fixtures(48);m96,_=fixtures()
        image,_=render(m48,camera)
        with self.assertRaises(DetectionError):analyze(image,m96,camera)

    def points(self,rows=6,columns=8,angle=0):
        grid=np.array([[c,r] for r in range(rows) for c in range(columns)],float)
        a=np.radians(angle)
        h=np.array([[90*np.cos(a),-85*np.sin(a),400],
                    [90*np.sin(a),85*np.cos(a),400],[.008,.005,1.]])
        points=cv2.perspectiveTransform(grid[None,:,:],h)[0]
        return points,grid,h

    def test_lattice_fit_tolerates_rotation_noise_and_missing_measurements(self):
        for angle in (0,20,80,170):
            points,_,_=self.points(angle=angle)
            noisy=points+np.random.default_rng(123).normal(0,.5,points.shape)
            noisy=np.delete(noisy,[9,20,37],axis=0)
            fit=fit_grid(noisy)
            self.assertEqual(len(fit['points']),45)
            self.assertLess(fit['rmse'],1.)

    def test_lattice_rejects_missing_row_random_points_and_duplicates(self):
        points,_,_=self.points()
        for bad in (points[8:],np.random.default_rng(4).uniform(0,1000,(48,2)),np.ones((48,2))):
            with self.assertRaises(DetectionError):fit_grid(bad)

    def test_wrong_96_layout_does_not_accept_48_centers(self):
        points,_,_=self.points()
        with self.assertRaises(DetectionError):fit_grid(points,8,12)

    def test_blank_image_has_no_virtual_landmarks(self):
        with self.assertRaises(DetectionError):preview(np.zeros((800,1200),np.uint8))

    def test_real_48_capture_is_pixel_only_and_preserves_uncertainty(self):
        path=Path(__file__).resolve().parents[3]/'operator_ui/reports/plate_projection_current/current_plate.png'
        if not path.exists():self.skipTest('Operator capture unavailable')
        result,_=preview(cv2.imread(str(path)))
        self.assertGreaterEqual(result['measured_wells'],40)
        self.assertLessEqual(result['measured_wells'],48)
        self.assertEqual(len(set(map(tuple,result['grid_indices']))),result['measured_wells'])
        self.assertFalse(result['orientation_resolved'])
        self.assertFalse(result['metric_pose_estimated'])
        self.assertFalse(result['motion_authorized'])
        self.assertNotIn('pose',result)
        self.assertNotIn('T_camera_plate',result)
        self.assertEqual(len(result['virtual_circles']),2)
        with self.assertRaisesRegex(DetectionError,'Image-only'):
            alignment_preview(result,{})


if __name__=='__main__':unittest.main(verbosity=2)
