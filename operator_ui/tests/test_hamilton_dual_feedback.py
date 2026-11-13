import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retry_hamilton_wider_release import raw_guard

class RawFeedbackTests(unittest.TestCase):
    def test_expected_outward_motion(self):
        raw_guard({1:90.3,2:-2.2},{1:90,2:-2})
        raw_guard({1:90.5,2:-2.5},{1:90,2:-2},arrival=True)

    def test_inward_jump_or_invalid_or_missing_arrival_rejected(self):
        for now, arrival in [({1:90,2:-.3},False),({1:float('nan'),2:-2},False),
                             ({1:90,2:-2},True),({1:91,2:-2.5},False)]:
            with self.assertRaises(RuntimeError):
                raw_guard(now,{1:90,2:-2},arrival=arrival)

if __name__ == '__main__': unittest.main()
