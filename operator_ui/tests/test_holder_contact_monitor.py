import unittest
from holder_contact_monitor import holder_ok

class HolderContactTests(unittest.TestCase):
    def test_recorded_dip_allowed_only_in_contact_phase(self):
        self.assertFalse(holder_ok(1.732844,1.77))
        self.assertTrue(holder_ok(1.732844,1.77,True))
        self.assertTrue(holder_ok(1.76855,1.77))

    def test_gross_motion_and_missing_feedback_still_stop(self):
        for value in (1.26,2.28,float('nan'),float('inf'),None):
            self.assertFalse(holder_ok(value,1.77,True))

    def test_hamilton_contact_bound_unchanged(self):
        self.assertTrue(holder_ok(90.3,90.716612))
        self.assertFalse(holder_ok(90,90.716612))
