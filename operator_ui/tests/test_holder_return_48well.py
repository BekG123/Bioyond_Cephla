"""Regression checks for the holder-return speed transition; no hardware."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from return_48well_holder import placement_speed


class ReturnSpeedTests(unittest.TestCase):
    def test_long_approach_ends_at_slow_zone_at_transfer_speed(self):
        self.assertEqual(placement_speed(dict(Z=300,Rz=89.662),dict(Z=93.712,Rz=89.662),73.712),137)

    def test_final_twenty_mm_are_slow(self):
        for start,end in [(93.712,78.716),(78.716,73.712)]:
            self.assertEqual(placement_speed(dict(Z=start,Rz=89.662),dict(Z=end,Rz=89.662),73.712),5)

    def test_clearance_wrist_speed(self):
        self.assertEqual(placement_speed(dict(Z=300,Rz=-3.88),dict(Z=300,Rz=19.5),73.712),30)


if __name__=='__main__':unittest.main()
