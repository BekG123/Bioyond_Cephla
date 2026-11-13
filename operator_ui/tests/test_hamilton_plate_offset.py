"""Offline regressions for plate layout, translation signs and placement targets."""
import sys
from pathlib import Path
import unittest
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hamilton_plate_offset import (FALCON48,FALCON96,OffsetError,fit_grid,
                                   detect_grid,candidate_translation,check_rim)

def sample(model=FALCON48,shift=(0,0),angle=0):
    cells=np.array([(c,r) for r in range(model.rows) for c in range(model.columns)])
    local=(cells-[(model.columns-1)/2,(model.rows-1)/2])*model.pitch_mm
    theta=np.radians(angle)
    rotation=np.array([[np.cos(theta),np.sin(theta)],[-np.sin(theta),np.cos(theta)]])
    return (local+shift)@rotation*5.5+[440,322]

class OffsetTests(unittest.TestCase):
    def test_recorded_site3_glare_preserves_layout_and_consistent_center(self):
        folder=Path(__file__).resolve().parents[1]/'reports/hamilton_api/dcg48_repeat_ce387777c9f144deb25b09b9c6679a71/cycle1_site3_before'
        files=list(folder.glob('site3_*.png'))
        if len(files)!=3:self.skipTest('Local recorded glare evidence not installed')
        centers=[]
        for path in files:
            gray=cv2.imread(str(path),0);result=detect_grid(gray,FALCON48)
            self.assertGreaterEqual(len(result['centers']),41)
            self.assertLessEqual(result['rms_pixels'],2.5)
            centers.append(result['transform'][2])
            with self.assertRaises(OffsetError):detect_grid(gray,FALCON96)
        self.assertLess(np.linalg.norm(np.ptp(centers,axis=0)),1)

    def test_ten_mm_source_shift_is_measured_not_hardcoded(self):
        for shift in ((10,0),(-10,0),(0,10),(3,-7),(0,0)):
            result=fit_grid(sample(shift=shift),FALCON48,71.5)
            measured=(result['transform'][2]-[440,322])@np.linalg.inv(result['transform'][:2])
            np.testing.assert_allclose(measured,shift,atol=1e-8)

    def test_rotation_is_reported_not_disguised_as_translation(self):
        result=fit_grid(sample(angle=3),FALCON48,71.5)
        self.assertAlmostEqual(result['angle_crop_deg'],3,places=5)

    def test_48_wells_cannot_pass_as_96(self):
        with self.assertRaises(OffsetError): fit_grid(sample(),FALCON96,49.5)

    def test_missing_outer_column_is_rejected(self):
        points=sample().reshape(6,8,2)[:,1:,:].reshape(-1,2)
        with self.assertRaises(OffsetError): fit_grid(points,FALCON48,71.5)

    def test_occluded_grid_is_rejected(self):
        with self.assertRaises(OffsetError): fit_grid(sample()[:30],FALCON48,71.5)

    def test_nonfinite_measurements_are_rejected(self):
        p=sample();p[3,0]=np.nan
        with self.assertRaises(OffsetError): fit_grid(p,FALCON48,71.5)

    def test_blank_camera_cannot_produce_correction(self):
        with self.assertRaises(OffsetError): detect_grid(np.zeros((645,879),np.uint8))

    def test_centered_pickup_keeps_destination_fixed(self):
        result=candidate_translation([62.1,44.63,24.19],[62.1,139.83,24.19],[-10,2])
        np.testing.assert_allclose(result['source_xyz'],[52.1,46.63,24.19])
        self.assertEqual(result['destination_xyz'],[62.1,139.83,24.19])
        self.assertFalse(result['executable'])

    def test_correction_does_not_accumulate_on_repeated_plans(self):
        source=[62.1,44.63,24.19];dest=[62.1,139.83,24.19]
        a=candidate_translation(source,dest,[10,0]);b=candidate_translation(source,dest,[10,0])
        self.assertEqual(a,b);self.assertEqual(source,[62.1,44.63,24.19])

    def test_grid_without_rim_is_not_seating_evidence(self):
        grid=fit_grid(sample(),FALCON48,71.5)
        rim=check_rim(np.zeros((645,879),np.uint8),grid,FALCON48)
        self.assertFalse(rim['accepted'])

    def test_live_capture_distinguishes_48_from_96(self):
        path=Path(__file__).resolve().parents[1]/'reports/hamilton_api/plate_offset_20261108T110717Z/site4_0.png'
        if not path.exists(): self.skipTest('Local recorded camera evidence not installed')
        gray=cv2.imread(str(path),0)
        result=detect_grid(gray,FALCON48)
        self.assertGreaterEqual(len(result['centers']),41)
        self.assertLess(result['offset_plate_axes_mm'][0],-7)
        self.assertGreater(result['offset_plate_axes_mm'][0],-11)
        with self.assertRaises(OffsetError): detect_grid(gray,FALCON96)

if __name__=='__main__': unittest.main()
