"""Calibration reference access must not authorize pending descent or grip."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plate48_workflow as w
from autonomy import TransferError


class PendingCalibrationTests(unittest.TestCase):
    def test_pending_reference_available_only_for_calibration(self):
        profile = dict(acceptance='fixture', acceptance_sha256='hash',
                       descent_status='supervised_open_claw_trial_pending')
        evidence = Mock()
        evidence.read_bytes.return_value = json.dumps(dict(fresh_alignment=dict(route=dict(
            target=dict(x=312, y=-64, rz=89))))).encode()
        with patch.object(w.pickup, 'load', return_value=(profile, 'profilehash')), \
             patch.object(w.pickup, 'evidence', return_value=evidence), \
             patch.object(w.pickup, 'accepted_grip', return_value=False):
            self.assertEqual(w.reference(require_grip=False, calibration_only=True)[1], 'profilehash')
            with self.assertRaises(TransferError): w.reference(require_grip=False)
            with self.assertRaises(TransferError): w.reference()
            with self.assertRaises(TransferError): w.reference(calibration_only=True)

    def test_missing_reviewed_reference_still_blocks_calibration(self):
        profile = dict(acceptance='fixture', acceptance_sha256='hash', descent_status='pending')
        evidence = Mock()
        evidence.read_bytes.return_value = b'{}'
        with patch.object(w.pickup, 'load', return_value=(profile, 'hash')), \
             patch.object(w.pickup, 'evidence', return_value=evidence):
            with self.assertRaises(TransferError): w.reference(require_grip=False, calibration_only=True)
