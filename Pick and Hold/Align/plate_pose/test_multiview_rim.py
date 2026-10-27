import unittest
from unittest.mock import patch
import cv2
import numpy as np
from multiview_rim import MultiViewRim
import test_rim_tracking
from project_taught_disks import transform
from vision import DetectionError

class MultiViewTests(unittest.TestCase):
    def fixture(self):
        image,q,outlines=test_rim_tracking.RimTests().fixture()
        anchors=[]
        for dx,dy in ((10,5),(-12,8)):
            h=np.array([[1.,0.,dx],[0.,1.,dy],[0.,0.,1.]])
            anchors.append((str(dx),cv2.warpPerspective(image,h,(1200,800),borderValue=(160,)*3)))
        return image,q,outlines,MultiViewRim(image,q,outlines,anchors)

    def test_known_geometry_and_return_without_updates(self):
        image,q,outlines,t=self.fixture()
        for dx,dy in ((20,-15),(-20,15),(0,0)):
            h=np.array([[1.,.004,dx],[-.004,1.,dy],[0.,0.,1.]])
            frame=cv2.warpPerspective(image,h,(1200,800),borderValue=(160,)*3)
            result=t.track(frame)
            np.testing.assert_allclose(result['corners_px'],transform(q,h),atol=1.)
            self.assertGreaterEqual(len(result['supporting_views']),2)
            self.assertEqual(result['reference_updates'],0)
            self.assertFalse(result['motion_authorized'])

    def test_single_view_cannot_authorize(self):
        image,_,_,t=self.fixture()
        with patch.object(t.views[1][1],'track',side_effect=DetectionError('lost')),patch.object(t.views[2][1],'track',side_effect=DetectionError('lost')):
            with self.assertRaisesRegex(DetectionError,'Fewer than two'):t.track(image)

    def test_disagreement_and_blank_reject(self):
        image,_,_,t=self.fixture()
        with self.assertRaises(DetectionError):t.track(np.zeros_like(image))
        # Corrupt an anchor transform; passing local fits must not hide disagreement.
        t.views[1][2][0,2]+=4
        with self.assertRaisesRegex(DetectionError,'disagree'):t.track(image)

if __name__=='__main__':unittest.main(verbosity=2)
