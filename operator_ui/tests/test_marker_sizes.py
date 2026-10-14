"""Offline regression: marker-specific sizes must not change camera calibration."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'grab_skill'))
import aruco_world as w

class Sizes(unittest.TestCase):
    def test_registry_and_override(self):
        rows=[dict(id=i,cam_xyz_mm=[1,2,100],side_px=50) for i in (1,3)]
        before=copy.deepcopy(w.CAL['eye_cam_fit'])
        with patch.object(w.A,'detect',return_value=rows):
            out=w.detect_sized('fake')
            self.assertAlmostEqual(out[0]['cam_xyz_mm'][2],100*20/w.SIZE_MM)
            self.assertEqual(out[1]['cam_xyz_mm'],[1,2,100])
            self.assertEqual(w.detect_sized('fake',25)[0]['marker_size_mm'],25)
            self.assertEqual(rows[0]['cam_xyz_mm'],[1,2,100])
            for value in (0,-1,float('nan')):
                with self.assertRaises(ValueError):w.detect_sized('fake',value)
        self.assertEqual(before,w.CAL['eye_cam_fit'])

if __name__=='__main__':unittest.main()
