"""Offline authorization evaluations. Ephemeral test keys never leave memory."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from signed_recovery import DSL, VERSION, FakeArm, RecoveryGate, Rejected, canonical, digest


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.arm = FakeArm()
        self.now = 1000
        self.db = Path(self.temp.name) / 'claims.sqlite'
        self.gate = RecoveryGate(self.public, self.db, self.arm, lambda: self.now)

    def package(self, source=DSL, **changes):
        m = dict(version=VERSION, dsl_sha256=digest(source), robot_id=self.arm.robot_id,
                 route_sha256=self.arm.route_sha256, request_id=uuid4().hex,
                 issued_at=1000, expires_at=1060)
        m.update(changes)
        sig = base64.b64encode(self.key.sign(canonical(m))).decode()
        return source, m, sig

    def test_valid(self):
        self.assertEqual(self.gate.execute(*self.package())['outcome'], 'fake_home_complete')
        self.assertEqual(self.arm.home_calls, 1)

    def test_fault_then_human_resolution_requires_new_signature(self):
        self.arm.faulted = True
        request = self.package()
        self.assertEqual(self.gate.execute(*request)['outcome'], 'paused_human_review')
        self.assertEqual(self.arm.home_calls, 0)
        self.arm.faulted = False  # Simulate a human resolving the fake fault.
        with self.assertRaises(Rejected): self.gate.execute(*request)
        self.assertEqual(self.gate.execute(*self.package())['outcome'], 'fake_home_complete')

    def test_tampered_dsl(self):
        source, m, sig = self.package()
        with self.assertRaises(Rejected): self.gate.execute(source + '\n', m, sig)
        self.assertEqual(self.arm.home_calls, 0)

    def test_modified_manifest(self):
        source, m, sig = self.package()
        m['expires_at'] += 1
        with self.assertRaises(Rejected): self.gate.execute(source, m, sig)

    def test_wrong_key(self):
        source, m, _ = self.package()
        sig = base64.b64encode(Ed25519PrivateKey.generate().sign(canonical(m))).decode()
        with self.assertRaises(Rejected): self.gate.execute(source, m, sig)

    def test_invalid_signature_encoding(self):
        source, m, _ = self.package()
        with self.assertRaises(Rejected): self.gate.execute(source, m, '!' * 88)

    def test_expired_future_and_overlong(self):
        for changes in ({'expires_at':1000}, {'issued_at':1001}, {'expires_at':1301}):
            with self.subTest(changes=changes), self.assertRaises(Rejected):
                self.gate.execute(*self.package(**changes))

    def test_wrong_robot_route_version(self):
        for k in ('robot_id', 'route_sha256', 'version'):
            with self.subTest(field=k), self.assertRaises(Rejected):
                self.gate.execute(*self.package(**{k:'wrong'}))

    def test_removed_guards_even_when_signed(self):
        for line in ('        STOP\n', '    REQUIRE gripper.empty\n', '    REQUIRE home.route_verified\n'):
            with self.subTest(line=line), self.assertRaises(Rejected):
                self.gate.execute(*self.package(source=DSL.replace(line, '')))

    def test_arbitrary_code_even_when_signed(self):
        with self.assertRaises(Rejected): self.gate.execute(*self.package(source='import os'))

    def test_payload_route_and_unknown_state(self):
        for attr, value, outcome in [('empty',False,'blocked_gripper_not_empty'),
                                     ('route_verified',False,'blocked_route_unverified'),
                                     ('faulted',None,'blocked_unknown_state')]:
            with self.subTest(attr=attr):
                old = getattr(self.arm, attr)
                setattr(self.arm, attr, value)
                self.assertEqual(self.gate.execute(*self.package())['outcome'], outcome)
                setattr(self.arm, attr, old)
        self.assertEqual(self.arm.home_calls, 0)

    def test_replay_after_gate_restart(self):
        request = self.package()
        self.gate.execute(*request)
        restarted = RecoveryGate(self.public, self.db, self.arm, lambda: self.now)
        with self.assertRaises(Rejected): restarted.execute(*request)

    def test_concurrent_replay_across_gate_instances(self):
        request = self.package()
        other = FakeArm()
        gate2 = RecoveryGate(self.public, self.db, other, lambda: self.now)
        def attempt(gate):
            try: return gate.execute(*request)['outcome']
            except Rejected: return 'rejected'
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(attempt, [self.gate, gate2]))
        self.assertCountEqual(results, ['fake_home_complete', 'rejected'])
        self.assertEqual(self.arm.home_calls + other.home_calls, 1)

    def test_crashed_claim_cannot_resume(self):
        source, m, sig = self.package()
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO requests VALUES (?, ?, ?, ?)',
                       (m['request_id'], json.dumps(m), self.now, 'claimed'))
        with self.assertRaises(Rejected): self.gate.execute(source, m, sig)

    def test_no_hardware_adapter(self):
        with self.assertRaises(TypeError): RecoveryGate(self.public, self.db, object())


if __name__ == '__main__':
    unittest.main(verbosity=2)
