"""Pure image tests; no robot, camera, or circle/marker localization."""
from pathlib import Path
import sys
import unittest
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plate_edges import detect_plate, plate_center


def scene(center=(550,350),angle=12):
    im=np.full((640,960,3),35,np.uint8)
    box=cv2.boxPoints((center,(420,280),angle)).astype(np.int32)
    cv2.fillConvexPoly(im,box,(190,190,190))
    # Interior marks must not become the plate rectangle.
    cv2.circle(im,tuple(np.asarray(center)+[-70,0]),35,(10,10,10),-1)
    cv2.circle(im,tuple(np.asarray(center)+[70,0]),18,(10,10,10),-1)
    return im


class PlateEdgesTests(unittest.TestCase):
    def test_offset_and_angle(self):
        result,_=detect_plate(scene())
        self.assertTrue(result['detected'],result)
        self.assertAlmostEqual(result['offset_px'][0],70.5,delta=3)
        self.assertAlmostEqual(result['offset_px'][1],30.5,delta=3)
        self.assertAlmostEqual(result['angle_image_deg'],12,delta=1)
        self.assertFalse(result['motion_authorized'])
    def test_centered(self):
        result,_=detect_plate(scene((480,320),0))
        self.assertTrue(result['detected'],result)
        self.assertLess(np.linalg.norm(result['offset_px']),3)
    def test_no_plate(self):
        result,_=detect_plate(np.zeros((640,960,3),np.uint8))
        self.assertFalse(result['detected'])
    def test_clipped_plate(self):
        result,_=detect_plate(scene((880,350),0))
        self.assertFalse(result['detected'])
    def test_multiple_rectangles_are_ambiguous(self):
        im=np.full((640,960,3),35,np.uint8)
        for x in (230,730):
            cv2.rectangle(im,(x-180,200),(x+180,440),(190,190,190),-1)
        result,_=detect_plate(im)
        self.assertFalse(result['detected'],result)
        self.assertGreaterEqual(result['candidate_count'],2)
    def test_circles_alone_are_not_a_plate(self):
        im=np.full((640,960,3),180,np.uint8)
        cv2.circle(im,(350,320),80,(10,10,10),-1)
        cv2.circle(im,(650,320),40,(10,10,10),-1)
        self.assertFalse(detect_plate(im)[0]['detected'])
    def test_marks_are_not_required(self):
        im=np.full((640,960,3),35,np.uint8)
        cv2.fillConvexPoly(im,cv2.boxPoints(((500,350),(420,280),-8)).astype(np.int32),(190,190,190))
        result,_=detect_plate(im)
        self.assertTrue(result['detected'],result)
        self.assertAlmostEqual(result['angle_image_deg'],-8,delta=1)
    def test_diagonal_center_respects_perspective(self):
        source=np.array([[0,0],[1,0],[1,1],[0,1]],np.float32)
        destination=np.array([[150,100],[700,130],[650,500],[200,550]],np.float32)
        matrix=cv2.getPerspectiveTransform(source,destination)
        actual=cv2.perspectiveTransform(np.array([[[.5,.5]]],np.float32),matrix)[0,0]
        np.testing.assert_allclose(plate_center(destination),actual,atol=.001)


if __name__ == '__main__':
    unittest.main()
