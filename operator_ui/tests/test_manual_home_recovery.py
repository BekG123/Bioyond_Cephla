"""Offline recovery lifecycle; no robot or network access."""
import json
import unittest
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_ik_home import IKHomeTests
from home_recovery import acknowledge, digest, recovered
from researcher_teaching import TeachingError


class ManualRecoveryTests(unittest.TestCase):
    def setUp(self):
        IKHomeTests.setUp(self)
        self.service.pose = self.home.target()[0]
        self.service.q = dict(J1=209.42, J2=84.88, J3=52.06, J4=-140.81)
        points = json.loads(self.path.read_text())
        points['points']['Home']['joint_reference'] = dict(self.service.q)
        self.path.write_text(json.dumps(points))
        self.service.e1 = .02
        self.state.update(enabled=False, program_state=dict(state='stopped'))
        self.connection.folder.mkdir()
        self.attempt = self.connection.folder/'failed.json'
        self.attempt.write_text(json.dumps(dict(status='failed_or_stopped',
            sequence=dict(state='error', result=dict(ok=False, error='joint soft limit')))))
        self.original = self.attempt.read_bytes()
        self.body = dict(reviewed_failure=True, empty_gripper=True, manual_home_confirmed=True,
                         review_notes='Reviewed actual turn failure; operator manually returned empty arm Home.',
                         attempts={'failed.json': digest(self.attempt)})

    def test_recovery_preserves_failure_and_sends_no_commands(self):
        self.assertTrue(acknowledge(self.connection, self.body)['ok'])
        self.assertEqual(self.attempt.read_bytes(), self.original)
        self.assertTrue(recovered(self.attempt))
        self.assertEqual(len(self.connection.history()), 1)
        self.assertEqual(self.service.moves, [])
        self.assertEqual(self.service.grips, [])
        self.assertEqual(self.rotations, [])
        self.assertFalse(self.state['enabled'])

    def test_reset_near_home_does_not_acknowledge(self):
        self.service.pose['Y'] += 10
        with self.assertRaises(TeachingError): acknowledge(self.connection, self.body)
        self.assertFalse(recovered(self.attempt))

    def test_wrong_joint_winding_blocked_even_at_same_tcp(self):
        self.service.q['J4'] += 360
        with self.assertRaises(TeachingError): acknowledge(self.connection, self.body)

    def test_fault_enabled_program_and_payload_block(self):
        for changes in (dict(errors=[3571]), dict(enabled=True), dict(program_state=dict(state='running'))):
            saved = deepcopy(self.state)
            self.state.update(changes)
            with self.assertRaises(TeachingError): acknowledge(self.connection, self.body)
            self.state.clear(); self.state.update(saved)
        self.service.e1 = 3.9
        with self.assertRaises(TeachingError): acknowledge(self.connection, self.body)

    def test_review_missing_or_stale_hash_blocked(self):
        for changes in (dict(reviewed_failure=False), dict(attempts={}), dict(review_notes='')):
            with self.assertRaises(TeachingError): acknowledge(self.connection, {**self.body, **changes})

    def test_new_failure_and_changed_original_still_block(self):
        acknowledge(self.connection, self.body)
        extra = self.connection.folder/'new-failure.json'
        extra.write_bytes(self.original)
        with self.assertRaises(TeachingError): self.connection.history()
        extra.unlink()
        self.attempt.write_text(self.original.decode() + ' ')
        with self.assertRaises(TeachingError): self.connection.history()

    def test_nonfinite_feedback_and_missing_reference_block(self):
        self.service.q['J1'] = float('nan')
        with self.assertRaises(TeachingError): acknowledge(self.connection, self.body)


if __name__ == '__main__':
    unittest.main()
