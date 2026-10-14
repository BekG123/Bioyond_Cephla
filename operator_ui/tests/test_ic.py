"""Numerical IC tests with known transforms; no camera or robot connection."""
import sys
from pathlib import Path
import unittest
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pick_and_hold.Align.ic import ICAligner, ICError, similarity


def fixture():
    a = np.full((480,640),175,np.uint8)
    cv2.circle(a,(230,230),53,30,-1)
    cv2.circle(a,(395,250),27,45,-1)
    cv2.rectangle(a,(140,135),(480,345),110,3)
    cv2.line(a,(155,320),(185,300),70,4)
    return cv2.GaussianBlur(a,(5,5),.8)


class ICTests(unittest.TestCase):
    def setUp(self):
        self.reference=fixture()
        self.roi=[120,110,390,260]
        self.engine=ICAligner(self.reference,self.roi)

    def test_identity(self):
        r=self.engine.align(self.reference)
        self.assertTrue(r['ok'],r)
        self.assertTrue(r['image_aligned'])

    def test_known_translation_rotation_scale_and_brightness(self):
        for dx,dy,angle,scale in [(8,-5,2,1.03),(-9,7,-3,.97),(.7,-.4,.3,1.)]:
            with self.subTest(transform=(dx,dy,angle,scale)):
                center=(315,240)
                warp=similarity(dx,dy,angle,scale,center)
                live=cv2.warpAffine(self.reference,warp[:2],(640,480),borderValue=175)
                live=np.clip(live.astype(float)*.85+17,0,255).astype(np.uint8)
                r=self.engine.align(live)
                self.assertTrue(r['ok'],r)
                self.assertAlmostEqual(r['shift_x_px'],dx,delta=.3)
                self.assertAlmostEqual(r['shift_y_px'],dy,delta=.3)
                self.assertAlmostEqual(r['rotation_deg'],angle,delta=.15)
                self.assertAlmostEqual(r['scale'],scale,delta=.003)
                self.assertFalse(r['motion_commanded'])

    def test_invalid_dark_reference_and_live(self):
        dark=np.full_like(self.reference,3)
        with self.assertRaises(ICError): ICAligner(dark,self.roi)
        with self.assertRaises(ICError): self.engine.align(dark)
        with self.assertRaises(ICError): self.engine.align(self.reference[:400])

    def test_occlusion_and_wrong_template_not_accepted(self):
        live=self.reference.copy()
        live[150:310,170:305]=175
        try: r=self.engine.align(live)
        except ICError: return
        self.assertFalse(r['ok'],r)

    def test_cancel_without_motion(self):
        with self.assertRaisesRegex(ICError,'cancelled'):
            self.engine.align(self.reference,cancel=lambda:True)


if __name__=='__main__': unittest.main()
