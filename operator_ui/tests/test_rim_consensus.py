"""No hardware calls: saved failure regression and edge-support rejection."""
import json
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from cellvis24_calibration import ROOT,reference,implementation_binding
from cellvis24_observation import rim_edges
from rim_edges import refine_consensus
from vision import DetectionError


class RimConsensusTests(unittest.TestCase):
    def test_saved_failure_refines_without_lowering_support_gate(self):
        d=reference()
        seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
        folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/7c29ef6a68724ffeb9a4365456a98e33'
        image=cv2.imread(str(folder/'prepared_median_1.png'))
        self.assertIsNotNone(image)
        image=cv2.resize(image,(1200,800))
        with patch('rim_edges.refine_consensus',side_effect=lambda x,c,b,i:(b,i)):
            with self.assertRaisesRegex(DetectionError,'103/160'):
                rim_edges(image,seed,[-1]*4)
        corners,edges=rim_edges(image,seed,[-1]*4)
        edge=edges[3]
        self.assertEqual(edge['initial_inliers'],103)
        self.assertEqual(edge['inliers'],104)
        self.assertTrue(edge['consensus_refined'])
        self.assertLessEqual(edge['rms_px'],.6)
        self.assertTrue(np.isfinite(corners).all())
        # Existing successful first burst must retain its exact fit.
        image=cv2.resize(cv2.imread(str(folder/'prepared_median_0.png')),(1200,800))
        with patch('rim_edges.refine_consensus',side_effect=lambda x,c,b,i:(b,i)):
            old,_=rim_edges(image,seed,[-1]*4)
        new,_=rim_edges(image,seed,[-1]*4)
        np.testing.assert_array_equal(old,new)

    def test_unobserved_edge_cannot_be_created_by_refitting(self):
        x=np.linspace(.12,.88,160)
        c=np.full((160,4),np.nan);c[:103,0]=0
        inside=np.arange(160)<103;indices=np.zeros(160,dtype=int)
        result,_=refine_consensus(x,c,inside,indices)
        self.assertEqual(result.sum(),103)

    def test_blank_and_missing_side_rejected(self):
        q=np.float32([[50,50],[350,50],[350,250],[50,250]])
        blank=np.full((300,400),200,np.uint8)
        with self.assertRaises(DetectionError):rim_edges(blank,q,[-1]*4)
        plate=blank.copy();cv2.rectangle(plate,(50,50),(350,250),20,-1)
        rim_edges(plate,q,[-1]*4)
        # Remove >half the left rim, leaving no valid distributed support.
        plate[85:220,:75]=20
        with self.assertRaises(DetectionError):rim_edges(plate,q,[-1]*4)

    def test_nonconvergence_does_not_accept_new_hypothesis(self):
        x=np.linspace(.12,.88,160);c=np.zeros((160,4))
        inside=np.arange(160)<100;indices=np.zeros(160,dtype=int)
        returned=refine_consensus(x,c,inside,indices,max_iterations=1)
        self.assertIs(returned[0],inside)

    def test_detector_changes_invalidate_pending_motion_preview(self):
        self.assertIn('Pick and Hold/Align/plate_pose/rim_edges.py',implementation_binding())


if __name__=='__main__':unittest.main()
