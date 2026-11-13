"""One adapter per machine. All three expose the same four calls.

    status()                              -> {state, detail, ts_utc, source}
    describe(operation=None)              -> manifest data
    run_operation(name, params, context)  -> {outcome, step_id, evidence_paths, ...}
    abort(context=None)                   -> best-effort stop, logged

A backend does the machine-specific work. It provides:
    read_status() -> {state, detail?, read_at?, sources?, source?}
    sensors()     -> {name: True | False | None}
    check(text)   -> True | False | None     (None: this backend cannot tell)
    bound(name)   -> bool                    (is this operation wired?)
    run(name, params, timeout_s) -> dict     (TimeoutError when the outcome is unknown)
    abort()       -> dict
    capture_frame(path) -> bool              (optional)
"""
from __future__ import annotations

import time

from .events import iso
from . import runner

STATES = ('busy', 'idle', 'error', 'unknown')


class MachineAdapter:
    def __init__(self, manifest, backend, clock=time.time, stale_after_s=10):
        self.manifest, self.backend, self.clock, self.stale_after_s = manifest, backend, clock, stale_after_s

    @property
    def id(self):
        return self.manifest.id

    def status(self):
        """unknown whenever the reading is missing, stale or contradictory."""
        now = self.clock()
        source = type(self.backend).__name__
        try:
            raw = self.backend.read_status()
        except Exception as error:
            return self._status('unknown', f'status read failed: {error}', now, source)
        if not isinstance(raw, dict):
            return self._status('unknown', 'status read returned nothing usable', now, source)
        source = raw.get('source', source)
        state, detail = raw.get('state'), raw.get('detail', '')
        sources = raw.get('sources') or {}
        age = now - raw.get('read_at', now)
        if state not in STATES:
            return self._status('unknown', f'missing or unrecognized state: {state!r}', now, source)
        if age > self.stale_after_s:
            return self._status('unknown', f'reading is {age:.0f} s old (limit {self.stale_after_s} s)', now, source)
        if len(set(sources.values())) > 1:
            return self._status('unknown', f'readings disagree: {sources}', now, source)
        return self._status(state, detail, now, source)

    def _status(self, state, detail, now, source):
        return dict(machine=self.id, state=state, detail=detail, ts_utc=iso(now), source=source)

    def describe(self, operation=None):
        m = self.manifest
        base = dict(machine=m.id, manifest_valid=m.valid)
        if not m.valid:
            base['manifest_errors'] = m.errors[:10]
        if operation is None:
            return dict(base, name=m.data.get('name'), summary=m.data.get('summary'), operations=[
                dict(name=op['name'], risk=op.get('risk'), description=op.get('description'),
                     qualification=m.qualification(op)[0], bound=self._bound(op['name']))
                for op in m.operations()])
        op = m.operation(operation)
        if op is None:
            return dict(base, error=f"unknown operation '{operation}'",
                        operations=[o['name'] for o in m.operations()])
        status, entry = m.qualification(op)
        limits = m.data.get('limits') if isinstance(m.data.get('limits'), dict) else {}
        return dict(base, operation=op, qualification=dict(entry, status=status), bound=self._bound(operation),
                    limits={p: limits[p] for p in (op.get('parameters') or {}) if p in limits},
                    known_faults=m.faults_affecting(operation), recovery=m.data.get('recovery', []))

    def _bound(self, name):
        try:
            return bool(self.backend.bound(name))
        except Exception:
            return False

    def run_operation(self, name, params=None, context=None):
        return runner.execute(self, name, params, context or runner.Context())

    def abort(self, context=None):
        context = context or runner.Context()
        try:
            detail, outcome = self.backend.abort(), 'abort_requested'
        except Exception as error:
            detail, outcome = dict(error=str(error)), 'abort_failed'
        context.events.emit('command', machine=self.id, step=context.step_id, op='abort', status=outcome,
                            data=detail if isinstance(detail, dict) else dict(detail=detail))
        return dict(outcome=outcome, machine=self.id, detail=detail)
