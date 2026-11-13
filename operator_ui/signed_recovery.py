"""Offline recovery experiment. No Flask routes, hardware imports, or signing keys.

This is a closed grammar for one recovery workflow, not a general DSL runtime.
It deliberately accepts only FakeArm; it cannot dispatch to the real robot.
"""
import base64
import hashlib
import json
import re
import sqlite3
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


DSL = """MACHINE arm
    IF arm.faulted
        PAUSE human.review
        STOP

    REQUIRE gripper.empty
    REQUIRE home.route_verified
    RUN arm.return_home
"""
VERSION = 'cephla.offline-recovery.v1'
FIELDS = {'version', 'dsl_sha256', 'robot_id', 'route_sha256',
          'request_id', 'issued_at', 'expires_at'}


class Rejected(ValueError):
    pass


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def canonical(manifest):
    return json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def parse(source):
    """Accept only the versioned, guarded Home recipe. Never eval/exec Python."""
    if not isinstance(source, str) or len(source) > 4096:
        raise Rejected('Invalid DSL size or type.')
    if [s for s in source.splitlines() if s] != [s for s in DSL.splitlines() if s]:
        raise Rejected('Unsupported recovery DSL. Keep all guards and indentation.')
    return ('fault_stop', 'require_empty', 'require_route', 'return_home')


class FakeArm:
    """Simulated observations and command log only; no network connection."""
    robot_id = 'fake-arm-1'
    route_sha256 = digest('fake saved Home route v1')

    def __init__(self, *, faulted=False, empty=True, route_verified=True):
        self.faulted = faulted
        self.empty = empty
        self.route_verified = route_verified
        self.home_calls = 0
        self.at_home = False
        self.lock = threading.RLock()


class RecoveryGate:
    def __init__(self, public_key, ledger, arm, clock=time.time):
        if type(arm) is not FakeArm:
            raise TypeError('Offline gate accepts only FakeArm.')
        self.key = Ed25519PublicKey.from_public_bytes(public_key)
        self.ledger, self.arm, self.clock = str(ledger), arm, clock
        # Persistent claim plus outcome. A crash after claim never authorizes retry.
        with sqlite3.connect(self.ledger) as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests ('
                       'id TEXT PRIMARY KEY, manifest TEXT NOT NULL, '
                       'claimed_at REAL NOT NULL, outcome TEXT NOT NULL)')

    def verify(self, source, manifest, signature):
        if type(manifest) is not dict or set(manifest) != FIELDS:
            raise Rejected('Unexpected authorization fields.')
        for k in FIELDS - {'issued_at', 'expires_at'}:
            if type(manifest[k]) is not str or len(manifest[k]) > 128:
                raise Rejected('Invalid authorization field.')
        for k in ('issued_at', 'expires_at'):
            if type(manifest[k]) is not int:
                raise Rejected('Authorization timestamps must be integer seconds.')
        if not re.fullmatch(r'[0-9a-f]{32}', manifest['request_id']):
            raise Rejected('Request ID must be a fresh 128-bit hexadecimal ID.')
        if type(signature) is not str or len(signature) != 88:
            raise Rejected('Invalid signature encoding.')
        try:
            raw = base64.b64decode(signature, validate=True)
            self.key.verify(raw, canonical(manifest))
        except (ValueError, InvalidSignature) as error:
            raise Rejected('Signature verification failed.') from error
        parse(source)
        if (manifest['version'] != VERSION or manifest['dsl_sha256'] != digest(source)
                or manifest['robot_id'] != self.arm.robot_id
                or manifest['route_sha256'] != self.arm.route_sha256):
            raise Rejected('Workflow, version, robot, or route does not match approval.')
        now = self.clock()
        if not (manifest['issued_at'] <= now < manifest['expires_at']
                and 0 < manifest['expires_at'] - manifest['issued_at'] <= 300):
            raise Rejected('Authorization expired, not yet valid, or exceeds five minutes.')

    def execute(self, source, manifest, signature):
        # Copy caller-owned data before validation to prevent mutation after verify.
        manifest = dict(manifest)
        with self.arm.lock:
            self.verify(source, manifest, signature)
            with sqlite3.connect(self.ledger, timeout=10) as db:
                try:
                    db.execute('INSERT INTO requests VALUES (?, ?, ?, ?)',
                               (manifest['request_id'], canonical(manifest).decode(),
                                self.clock(), 'claimed'))
                except sqlite3.IntegrityError as error:
                    raise Rejected('Request already consumed. Create a fresh signed request.') from error
            # Claim is durable before checking state or simulating an action.
            # Unknown observations fail closed, independently of DSL content.
            if any(type(v) is not bool for v in
                   (self.arm.faulted, self.arm.empty, self.arm.route_verified)):
                result = 'blocked_unknown_state'
            elif self.arm.faulted:
                result = 'paused_human_review'
            elif not self.arm.empty:
                result = 'blocked_gripper_not_empty'
            elif not self.arm.route_verified:
                result = 'blocked_route_unverified'
            elif not manifest['issued_at'] <= self.clock() < manifest['expires_at']:
                result = 'blocked_expired_before_dispatch'
            else:
                self.arm.home_calls += 1
                self.arm.at_home = True
                result = 'fake_home_complete'
            with sqlite3.connect(self.ledger) as db:
                db.execute('UPDATE requests SET outcome=? WHERE id=?',
                           (result, manifest['request_id']))
            return dict(request_id=manifest['request_id'], outcome=result,
                        hardware_motion=False, fake_home_calls=self.arm.home_calls)
