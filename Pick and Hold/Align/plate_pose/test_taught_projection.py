"""Saved-image projection tests; no robot or camera connection."""
import unittest
import cv2
import numpy as np
from project_taught_disks import measure_disks, project, transform
from vision import DetectionError


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.corners=np.array([[20,20],[480,20],[480,280],[20,280]],np.float32)
        self.image=np.full((300,500,3),210,np.uint8)
        cv2.circle(self.image,(170,150),42,(25,25,25),-1)
        cv2.circle(self.image,(330,150),21,(25,25,25),-1)
        self.seeds={'large':[170,150],'small':[330,150]}

    def test_measured_disks_preserve_original_geometry(self):
        outlines,_=measure_disks(self.image,self.corners,self.seeds)
        for label,center,radius in [('large',[170,150],42),('small',[330,150],21)]:
            self.assertLess(np.max(abs(np.linalg.norm(outlines[label]-center,axis=1)-radius)),1.1)

    def test_known_projective_mapping_and_roundtrip(self):
        outlines,_=measure_disks(self.image,self.corners,self.seeds)
        known=np.array([[1.2,.15,90],[-.1,.9,50],[.0004,.0007,1]])
        target=transform(self.corners,known)
        h,mapped=project(self.corners,target,outlines)
        for label in outlines:
            np.testing.assert_allclose(mapped[label],transform(outlines[label],known),atol=1e-4)
            np.testing.assert_allclose(transform(mapped[label],np.linalg.inv(h)),outlines[label],atol=1e-6)

    def test_blank_wrong_labels_and_duplicate_seeds_rejected(self):
        with self.assertRaises(DetectionError):
            measure_disks(np.full_like(self.image,210),self.corners,self.seeds)
        with self.assertRaises(DetectionError):
            measure_disks(self.image,self.corners,{'large':[330,150],'small':[170,150]})
        with self.assertRaises(DetectionError):
            measure_disks(self.image,self.corners,{'large':[170,150],'small':[170,150]})

    def test_mirror_and_degenerate_correspondence_rejected(self):
        outlines,_=measure_disks(self.image,self.corners,self.seeds)
        with self.assertRaises(DetectionError): project(self.corners,self.corners[::-1],outlines)
        with self.assertRaises(DetectionError): project(self.corners,np.zeros((4,2)),outlines)

    def test_projection_horizon_rejected(self):
        with self.assertRaises(DetectionError):
            transform([[0,0],[1,0]],[[1,0,0],[0,1,0],[1,0,0]])


if __name__=='__main__': unittest.main(verbosity=2)
