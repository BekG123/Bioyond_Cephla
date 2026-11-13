"""Durable MCP request receipts. Recover replies, never replay uncertain work.

An executing receipt is committed BEFORE invoking a tool. Only explicit lock
refusals can return it to queued. A crash leaves executing requests unresolved;
a later process cannot infer that the operation failed or repeat it.
"""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

READ_ONLY_TOOLS = frozenset({
    'get_workflow_catalog', 'lacry_state', 'get_lab_status', 'lab_describe',
    'search_memory', 'lacry_recovery_status',
})
RETRYABLE_CODES = frozenset({'tool_busy', 'control_busy', 'request_in_progress'})
REQUEST_ID = re.compile(r'^[0-9a-f]{32}$')


def refusal(code, message, *, retryable=False, outcome='not_dispatched'):
    return dict(ok=False, message=message, recovery=dict(
        code=code, retryable=retryable, dispatch_outcome=outcome,
        next_action='retry_same_request' if retryable else 'inspect_state'))


class RequestJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.owner = uuid4().hex
        self.stop_pending = False
        self.uncertain_ids = set()
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, tool TEXT NOT NULL,
                state TEXT NOT NULL, owner TEXT NOT NULL, epoch INTEGER NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL,
                response TEXT, status_code INTEGER)''')
            db.execute('CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY, epoch INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO control VALUES (1, 0)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def begin(self, ident, name, arguments):
        """Return a cached/refused (payload, HTTP status), or claim once with None."""
        if self.stop_pending:
            self.cancel_waiters()
        fingerprint = hashlib.sha256(json.dumps(
            [name, arguments], sort_keys=True, allow_nan=False).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM requests WHERE id=?', (ident,)).fetchone()
            epoch = db.execute('SELECT epoch FROM control WHERE id=1').fetchone()[0]
            if row:
                if row['fingerprint'] != fingerprint:
                    return refusal('request_conflict', 'Request ID belongs to different arguments.'), 409
                if row['state'] == 'completed':
                    value = json.loads(row['response'])
                    value.setdefault('recovery', {}).update(request_id=ident, receipt_replayed=True)
                    return value, row['status_code']
                if row['state'] == 'executing':
                    live = row['owner'] == self.owner and ident not in self.uncertain_ids
                    return refusal('request_in_progress' if live else 'outcome_unknown',
                        'The original tool is still running.' if live else
                        'This tool has no durable outcome. Inspect current state; do not repeat it.',
                        retryable=live, outcome='in_progress' if live else 'unknown'), 409
                if (row['epoch'] != epoch or row['owner'] != self.owner) and name not in READ_ONLY_TOOLS and name != 'lacry_stop':
                    value = refusal('cancelled_by_stop', 'Stop cancelled this queued request.')
                    if row['owner'] != self.owner:
                        value = refusal('cancelled_by_restart', 'Backend restart cancelled this queued request.')
                    db.execute("UPDATE requests SET state='completed', response=?, status_code=409, updated=? WHERE id=?",
                               (json.dumps(value), time.time(), ident))
                    return value, 409
                db.execute("UPDATE requests SET state='executing', owner=?, updated=? WHERE id=?",
                           (self.owner, time.time(), ident))
            else:
                now = time.time()
                db.execute('INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)',
                           (ident, fingerprint, name, 'executing', self.owner, epoch, now, now))
        return None

    def finish(self, ident, value, status, *, queued=False):
        result = deepcopy(value)
        result.setdefault('recovery', {}).update(request_id=ident, receipt_replayed=False)
        encoded = json.dumps(result, allow_nan=False)
        with self.connect() as db:
            db.execute('UPDATE requests SET state=?, response=?, status_code=?, updated=? WHERE id=?',
                       ('queued' if queued else 'completed', encoded, status, time.time(), ident))
        return result, status

    def cancel_waiters(self):
        # Keep Stop effective even when storage is temporarily unavailable.
        # The next request must persist this barrier before it can dispatch.
        self.stop_pending = True
        with self.connect() as db:
            db.execute('UPDATE control SET epoch=epoch+1 WHERE id=1')
        self.stop_pending = False

    def mark_uncertain(self, ident):
        # If the result could not be committed, do not pretend its tool is still
        # running or keep polling it. Across restart the owner marker does this.
        self.uncertain_ids.add(ident)

    def status(self, request_id=None):
        with self.connect() as db:
            if request_id is not None:
                row = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
                if row is None:
                    return dict(ok=True, found=False, request_id=request_id,
                                message='No receipt is available; absence alone does not authorize repeating an operation.')
                state = row['state']
                if state == 'executing' and (row['owner'] != self.owner or request_id in self.uncertain_ids):
                    state = 'outcome_unknown'
                return dict(ok=True, found=True, request_id=request_id, tool=row['tool'], state=state,
                            response=json.loads(row['response']) if state == 'completed' else None,
                            http_status=row['status_code'] if state == 'completed' else None)
            counts = {row[0]: row[1] for row in db.execute('SELECT state, COUNT(*) FROM requests GROUP BY state')}
            rows = db.execute('SELECT id, tool, state, owner, updated FROM requests ORDER BY updated DESC LIMIT 20').fetchall()
        recent = []
        for row in rows:
            item = dict(row)
            owner = item.pop('owner')
            if item['state'] == 'executing' and (owner != self.owner or item['id'] in self.uncertain_ids):
                item['state'] = 'outcome_unknown'
            recent.append(item)
        return dict(ok=True, automatic_recovery=True,
            scope='MCP transport, pre-dispatch contention, and saved tool replies',
            counts=counts, recent=recent,
            policy=dict(retry_same_request=True, replay_uncertain_operation=False,
                        stop_cancels_queued_mutations=True, automatic_fault_reset=False,
                        automatic_physical_resume=False),
            next_action='Read lacry_state and get_lab_status for physical workflow status. '
                        'A saved tool reply is not evidence of completed hardware work.')
