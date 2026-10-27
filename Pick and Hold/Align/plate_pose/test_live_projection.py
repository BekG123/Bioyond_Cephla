import unittest
import cv2
import numpy as np
from live_projection import Tracker
from project_taught_disks import transform
from vision import DetectionError


class LiveProjectionTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(9)
        self.image=np.full((800,1200,3),180,np.uint8)
        for x,y,r in rng.integers([160,160,3],[1040,640,16],size=(350,3)):
            cv2.circle(self.image,(int(x),int(y)),int(r),(int(r)*8,)*3,-1)
        self.q=np.float32([[120,120],[1080,120],[1080,680],[120,680]])
        self.outlines={'large':[[360,350],[400,310],[440,350],[400,390]],
                       'small':[[730,350],[750,330],[770,350],[750,370]]}
        self.tracker=Tracker(self.image,self.q,self.outlines)

    def test_tracks_independent_known_motion_without_motion_authorization(self):
        h=np.array([[.98,.02,15],[-.015,.99,18],[.00001,.00001,1.]])
        moved=cv2.warpPerspective(self.image,h,(1200,800),borderValue=(180,180,180))
        result=self.tracker.track(moved)
        np.testing.assert_allclose(result['corners_px'],transform(self.q,h),atol=1.2)
        self.assertFalse(result['motion_authorized'])
        self.assertFalse(result['metric_pose_estimated'])
        for c in result['virtual_circles']:
            np.testing.assert_allclose(c['pixels'],transform(self.outlines[c['label']],h),atol=.8)

    def test_missing_features_rejects_instead_of_holding_old_target(self):
        self.tracker.track(self.image)
        with self.assertRaises(DetectionError): self.tracker.track(np.zeros_like(self.image))

    def test_resolution_aspect_change_rejected(self):
        with self.assertRaises(DetectionError): self.tracker.track(self.image[:400])


if __name__=='__main__': unittest.main(verbosity=2)
