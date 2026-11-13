"""Fixed per-profile ROI: measured evidence, stable reference, and rejection."""
import json,unittest
from unittest.mock import patch
from copy import deepcopy
import cv2,numpy as np
from cellvis24_calibration import ROOT,reference,projected_solution,OBSERVATION,RIM_SAMPLE_SPAN
from cellvis24_observation import measure,summarize,teach
from cellvis24_image_pipeline import median5,decode_reference
from build_cellvis24_camera_reference_v3 import build
from rim_edges import rim_edges
from vision import DetectionError

class CellvisRimRoiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=reference();cls.seed=json.loads((ROOT/cls.d['files']['seed']['path']).read_bytes())['fitted']
        cls.disks=json.loads((ROOT/cls.d['files']['disks']['path']).read_bytes())
        cls.cfg=next(c for c in teach._configs() if c['name']=='Wide')

    def measurement(self,image):
        return measure(image,self.seed,self.disks,OBSERVATION,self.cfg,rim_sample_span=RIM_SAMPLE_SPAN,rim_tangent_radius=2)

    def test_failed_run_passes_same_quality_checks_on_fixed_straight_roi(self):
        p=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/a04cc11d024b4461b295820402b30245/prepared_median_0.png'
        image=cv2.imread(str(p));self.assertIsNotNone(image)
        with self.assertRaisesRegex(DetectionError,'103/160'):
            measure(image,self.seed,self.disks,OBSERVATION,self.cfg)
        m=self.measurement(image)
        self.assertGreaterEqual(m['measured_wells'],20)
        for e in m['edges']:
            self.assertGreaterEqual(e['inliers'],104)
            self.assertGreaterEqual(min(e['support_bins']),15)
            self.assertLessEqual(e['rms_px'],.6)
            self.assertEqual(e['sample_span'],[.25,.75])

    def test_three_stationary_bursts_are_stable_and_within_trial_scope(self):
        for name in ['rim_consensus_1794447406716340500','rim_consensus_1794447736863324000','rim_consensus_1794447906966131400']:
            with self.subTest(name=name):
                folder=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'/name
                ms=[self.measurement(cv2.imread(str(folder/f'median_{i}.png'))) for i in range(3)]
                s=summarize(ms);self.assertTrue(s['stationary_checks_passed'])
                self.assertLess(s['target_xy_spread_mm'],.25)
                solution=projected_solution(ms)
                self.assertLessEqual(solution['endpoint_shift_mm'],1.)
                self.assertFalse(solution['grip_authorized'])

    def test_reference_rebuilt_from_same_frames_preserves_taught_grasp(self):
        rebuilt=build();self.assertEqual(rebuilt,self.d)
        m=deepcopy(rebuilt['reference_reproduction'][2]['measurement'])
        s=projected_solution([deepcopy(m) for _ in range(3)])
        self.assertAlmostEqual(s['endpoint_shift_mm'],0,places=8)
        for k in s['endpoint']:self.assertAlmostEqual(s['endpoint'][k],s['taught_endpoint'][k],places=9)
        self.assertEqual(self.d['reuse_xy_mm'],.5)
        self.assertEqual(self.d['reuse_yaw_deg'],.2)

    def test_missing_center_and_blank_remain_rejected(self):
        q=np.float32([[50,50],[350,50],[350,250],[50,250]])
        blank=np.full((300,400),200,np.uint8)
        with self.assertRaises(DetectionError):rim_edges(blank,q,[-1]*4,sample_span=RIM_SAMPLE_SPAN,tangent_radius=2)
        image=blank.copy();cv2.rectangle(image,(50,50),(350,250),20,-1)
        rim_edges(image,q,[-1]*4,sample_span=RIM_SAMPLE_SPAN,tangent_radius=2)
        image[100:200,:75]=20
        with self.assertRaises(DetectionError):rim_edges(image,q,[-1]*4,sample_span=RIM_SAMPLE_SPAN,tangent_radius=2)

    def test_roi_cannot_shrink_to_a_tiny_patch(self):
        with self.assertRaises(ValueError):rim_edges(np.zeros((50,50),np.uint8),self.seed,sample_span=(.4,.6))

    def test_known_translation_remains_measured(self):
        q=np.float32([[50,50],[350,50],[350,250],[50,250]])
        image=np.full((300,400),200,np.uint8);cv2.rectangle(image,(50,50),(350,250),20,-1)
        opts=dict(polarities=[-1]*4,sample_span=RIM_SAMPLE_SPAN,tangent_radius=2)
        a,_=rim_edges(image,q,**opts)
        shifted=cv2.warpAffine(image,np.float32([[1,0,2],[0,1,-3]]),(400,300),borderValue=200)
        b,_=rim_edges(shifted,q,**opts)
        np.testing.assert_allclose(b-a,np.tile([2.,-3.],(4,1)),atol=.15)

    def test_roi_and_reference_must_match(self):
        bad=deepcopy(self.d);bad['rim_sample_span']=[.2,.8]
        with patch('cellvis24_calibration.json.loads',return_value=bad):
            with self.assertRaisesRegex(Exception,'pipeline mismatch'):reference()
