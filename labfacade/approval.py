"""Who said yes, to what, and until when.

A person approves a plan once. That approval is a bounded authorization: a
hash of the plan, the exact steps and parameters it covers, and an expiry.
Everything a person grants is written by HumanConsole and signed with a key
the console holds. The Facade only verifies. It has no way to grant.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import secrets
import time

from .events import iso


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def plan_hash(plan):
    return hashlib.sha256(canonical(plan).encode()).hexdigest()


class Signer:
    def __init__(self, key):
        if not isinstance(key, bytes) or len(key) < 16:
            raise ValueError('signing key must be at least 16 bytes')
        self._key = key

    @classmethod
    def from_file(cls, path, create=False):
        path = Path(path)
        if create and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(secrets.token_bytes(32))
        return cls(path.read_bytes())

    def sign(self, record):
        body = {k: v for k, v in record.items() if k != 'sig'}
        return dict(body, sig=hmac.new(self._key, canonical(body).encode(), hashlib.sha256).hexdigest())

    def verify(self, record):
        if not isinstance(record, dict) or not isinstance(record.get('sig'), str):
            return False
        return hmac.compare_digest(self.sign(record)['sig'], record['sig'])


class HumanConsole:
    """The only place approvals are created. Give this to the UI, never to the agent."""

    def __init__(self, run, signer, clock=time.time):
        self.run, self.signer, self.clock = run, signer, clock

    def approve_plan(self, approver, ttl_s=8 * 3600):
        plan, now = self.run.plan, self.clock()
        steps = plan.get('steps', [])
        record = self.signer.sign(dict(
            type='plan_approval', run=self.run.run_id, plan_hash=plan_hash(plan), approver=approver,
            approved_at=now, expires_at=now + ttl_s,
            allowed=[dict(step=s['id'], machine=s['machine'], operation=s['operation'],
                          params=s.get('params') or {}) for s in steps],
            machines=sorted({s['machine'] for s in steps}), plates=plan.get('plates') or {}))
        self.run.write_json('approval.json', record)
        self.run.events.emit('approval', status='plan_approved', data=dict(
            approver=approver, plan_hash=record['plan_hash'], expires=iso(record['expires_at'])))
        return record

    def attest_presence(self, person, ttl_s=4 * 3600, heartbeat_s=300):
        now = self.clock()
        record = self.signer.sign(dict(type='presence', run=self.run.run_id, person=person, attested_at=now,
                                       expires_at=now + ttl_s, heartbeat_s=heartbeat_s, last_heartbeat=now))
        self.run.write_json('attestation.json', record)
        self.run.events.emit('approval', status='presence_attested', data=dict(
            person=person, expires=iso(record['expires_at']), heartbeat_s=heartbeat_s))
        return record

    def heartbeat(self, person):
        record, now = self.run.read_json('attestation.json'), self.clock()
        if not self.signer.verify(record) or record['person'] != person or now >= record['expires_at']:
            raise PermissionError('No valid presence attestation for this person. Attest again.')
        record = self.signer.sign(dict(record, last_heartbeat=now))
        self.run.write_json('attestation.json', record)
        self.run.events.emit('approval', status='heartbeat', data=dict(person=person))
        return record

    def confirm(self, step_id, text, person, ttl_s=120):
        """A fresh answer to one question about one step. It expires quickly."""
        now = self.clock()
        self._append(dict(type='confirmation', step=step_id, text=text, person=person, at=now,
                          expires_at=now + ttl_s))
        self.run.events.emit('approval', step=step_id, status='confirmed', data=dict(person=person, text=text))

    def override(self, step_id, person, reason):
        """Let one step run although its operation is blocked, untested or under review."""
        self._append(dict(type='override', step=step_id, person=person, reason=reason, at=self.clock()))
        self.run.events.emit('approval', step=step_id, status='override_granted',
                             data=dict(person=person, reason=reason))

    def resume(self, person, reason):
        pause = open_pause(self.run, self.signer)
        if pause is None:
            raise ValueError('This run is not paused.')
        self._append(dict(type='resume', pause_seq=pause['seq'], person=person, reason=reason, at=self.clock()))
        self.run.events.emit('resume', step=pause.get('step'), status='resumed',
                             data=dict(person=person, reason=reason, pause_seq=pause['seq']))

    def _append(self, record):
        record = self.signer.sign(dict(record, run=self.run.run_id))
        with (self.run.path / 'human.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, allow_nan=False) + '\n')


# --- verification, used by the facade -------------------------------------------------

def approval_problem(run, signer, now, step_id, machine, operation, params):
    """(code, reason) when this exact call is not covered by a valid plan approval."""
    record = run.read_json('approval.json')
    if record is None:
        return 'no_approval', 'No approved plan for this run.'
    if not signer.verify(record) or record.get('type') != 'plan_approval' or record.get('run') != run.run_id:
        return 'approval_invalid', 'The approval record is not one this console signed for this run.'
    if now >= record['expires_at']:
        return 'approval_expired', f"The plan approval expired at {iso(record['expires_at'])}."
    if record['plan_hash'] != plan_hash(run.plan):
        return 'plan_changed', 'The plan was changed after approval. It needs a new approval.'
    wanted = dict(step=step_id, machine=machine, operation=operation, params=params or {})
    if not any(canonical(entry) == canonical(wanted) for entry in record['allowed']):
        return 'not_in_approved_plan', 'This step, operation or parameter set is not in the approved plan.'
    return None


def attestation_problem(run, signer, now):
    record = run.read_json('attestation.json')
    if record is None:
        return 'No one has attested they are at the E-stop for this run.'
    if not signer.verify(record) or record.get('type') != 'presence' or record.get('run') != run.run_id:
        return 'The presence attestation is not one this console signed for this run.'
    if now >= record['expires_at']:
        return f"The presence attestation expired at {iso(record['expires_at'])}."
    if now - record['last_heartbeat'] > record['heartbeat_s']:
        return (f"No heartbeat for {int(now - record['last_heartbeat'])} s "
                f"(limit {record['heartbeat_s']} s).")
    return None


def _human_records(run, signer, kind):
    path = run.path / 'human.jsonl'
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if signer.verify(record) and record.get('type') == kind and record.get('run') == run.run_id:
            records.append(record)
    return records


def confirmed(run, signer, now, step_id, text):
    return any(r['step'] == step_id and r['text'] == text and now < r['expires_at']
               for r in _human_records(run, signer, 'confirmation'))


def overridden(run, signer, step_id):
    return any(r['step'] == step_id for r in _human_records(run, signer, 'override'))


def open_pause(run, signer):
    """The earliest pause no person has resumed, or None."""
    resumed = {r['pause_seq'] for r in _human_records(run, signer, 'resume')}
    return next((e for e in run.events.read() if e['kind'] == 'pause' and e['seq'] not in resumed), None)
