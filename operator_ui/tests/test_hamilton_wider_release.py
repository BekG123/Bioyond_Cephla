import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_hamilton_wider_release import MoveYRelative,total_target,C

class WiderReleaseTests(unittest.TestCase):
    def test_total_is_fifteen_not_fifteen_more(self):
        start,end=total_target(4),total_target(15)
        for c,sign in ((1,1),(2,-1)):
            self.assertAlmostEqual((end[c]['position_y']-start[c]['position_y'])*sign,11)
            self.assertEqual(start[c]['position_z'],end[c]['position_z'])
            self.assertEqual(start[c]['position_x'],end[c]['position_x'])
    def test_no_large_or_inward_relative_command(self):
        for distance in (-.5,0,1,11):
            with self.assertRaises(ValueError):MoveYRelative(distance).build_parameters()
        decoded=C.HoiParamsParser(MoveYRelative(.5).build_parameters().build()).parse_all()
        self.assertEqual(len(decoded),2)
        self.assertEqual(decoded[-1][1],1)

if __name__=='__main__':unittest.main()
