"""Candidate sensitivity changes must retain geometric rejection and disk math."""
import json
import unittest
from pathlib import Path
import cv2
import numpy as np
from cellvis24_observation import detect,measure,teach,ROOT
from cellvis24_calibration import reference,OBSERVATION
from cellvis24_image_pipeline import decode_reference,median5
from vision import DetectionError


class GridCrosscheckTests(unittest.TestCase):
    def test_blank_noise_and_partial_grid_rejected(self):
        rng=np.random.default_rng(72)
        blank=np.zeros((800,1200),np.uint8)
        partial=blank.copy()
        for r in range(2):
            for c in range(6):cv2.circle(partial,(350+115*c,220+115*r),46,255,3)
        for image in [blank,rng.integers(0,256,blank.shape,dtype=np.uint8),partial]:
            with self.subTest(image=int(image.sum())),self.assertRaises(DetectionError):
                detect(image,4,6,candidate_votes=24)

    def test_offline_failure_recovers_grid_without_changing_rim_math(self):
        folder=ROOT/'operator_ui/reports/plate_session/cellvis24_adjustments/59cf68706a604467ab9ff5113f421f0d'
        file=folder/'trial/prepared_median_0.png'
        if not file.exists():self.skipTest('Local failed trial image unavailable')
        image=cv2.imread(str(file))
        with self.assertRaises(DetectionError):detect(image,4,6)
        fit=detect(image,4,6,candidate_votes=24)
        self.assertEqual(len(fit['points']),24);self.assertLess(fit['rmse'],8)
        for p in folder.glob('prepared_median_*.png'):
            fit=detect(cv2.imread(str(p)),4,6,candidate_votes=24)
            self.assertGreaterEqual(len(fit['points']),20);self.assertLess(fit['rmse'],8)

    def test_original_projected_target_is_unchanged(self):
        folder=ROOT/'operator_ui/reports/plate_session/cellvis24_validation/observation_53eb4e48abd6'
        if not folder.exists():self.skipTest('Commissioning images unavailable')
        d=json.loads((ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis24_camera_reference_v2.json').read_bytes());seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
        disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes())
        cfg=next(c for c in teach._configs() if c['name']=='Wide')
        image=median5([decode_reference((folder/f'burst_2_{j}.jpg').read_bytes()) for j in range(5)])
        m=measure(image,seed,disks,OBSERVATION,cfg)
        for k in ('x','y','rz'):self.assertAlmostEqual(m['target'][k],d['raw_target'][k],places=9)
        self.assertGreaterEqual(m['measured_wells'],20);self.assertLess(m['grid_rmse_px'],8)


if __name__=='__main__':unittest.main()
