"""Offline sign/frame checks for measured gap correction; no hardware."""
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_gap_centering import centering_delta
from autonomy import TransferError
from execute_adapted_descent import validate_completed_alignment


class GapCenteringTests(unittest.TestCase):
    def test_top_view_big_above_small_shifts_left(self):
        delta, proof = centering_delta([0,10,0],[0,-10,0],0,[1.5,2],[3,3.5])
        self.assertAlmostEqual(delta['X'],-.75)
        self.assertAlmostEqual(delta['Y'],0)
        self.assertEqual(proof['distance_range_mm'],[.5,1.])
        # Shift left increases the smaller left gap and reduces the right gap.
        self.assertAlmostEqual(1.75-delta['X'],3.25+delta['X'])

    def test_rotating_camera_pose_rotates_correction(self):
        delta,_=centering_delta([0,10,0],[0,-10,0],90,[1.5,2],[3,3.5])
        self.assertAlmostEqual(delta['X'],0)
        self.assertAlmostEqual(delta['Y'],-.75)
        self.assertAlmostEqual(math.hypot(*delta.values()),.75)

    def test_translation_of_disk_centers_does_not_change_direction(self):
        a,_=centering_delta([5,15,2],[5,-5,2],34,[1.5,2],[3,3.5])
        b,_=centering_delta([0,10,0],[0,-10,0],34,[1.5,2],[3,3.5])
        self.assertEqual(a,b)

    def test_ambiguous_gap_or_direction_rejected(self):
        cases=[([0,0,0],[0,0,0],[1.5,2],[3,3.5]),
               ([0,10,0],[0,-10,0],[3,3.5],[1.5,2]),
               ([0,10,0],[0,-10,0],[1.5,2],[1.8,3]),
               ([0,10,0],[0,-10,0],[1.5,2],[5,6])]
        for big,small,left,right in cases:
            with self.subTest(left=left,right=right),self.assertRaises(TransferError):
                centering_delta(big,small,0,left,right)

    def test_completed_alignment_requires_actual_matching_success(self):
        target=dict(x=300,y=-70,config='Wide',converged=True)
        review=dict(state=dict(target=target))
        seq=dict(active=False,name='researcher_align',state='done',result=dict(ok=True),target=target)
        validate_completed_alignment(seq,review)
        for changed in (dict(active=True),dict(state='error'),dict(result=dict(ok=False)),
                        dict(name='find_disk'),dict(target={**target,'x':301})):
            with self.subTest(changed=changed),self.assertRaises(RuntimeError):
                validate_completed_alignment({**seq,**changed},review)


if __name__=='__main__':
    unittest.main()
