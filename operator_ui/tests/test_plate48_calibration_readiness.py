import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plate48_workflow as w

class CalibrationReadinessTests(unittest.TestCase):
    def test_inspected_descent_allows_calibration_but_not_full_pickup(self):
        with patch.object(w.pickup,'accepted_grip',return_value=None):
            p,_,_=w.reference(require_grip=False)
            self.assertEqual(p['descent_status'],'operator_accepted_open_claw_descent')
            with self.assertRaises(w.TransferError):w.reference()
    def test_unaccepted_descent_still_refused(self):
        p,d=w.pickup.load();p['descent_status']='pending'
        with patch.object(w.pickup,'load',return_value=(p,d)):
            with self.assertRaises(w.TransferError):w.reference(require_grip=False)

if __name__=='__main__':unittest.main()
