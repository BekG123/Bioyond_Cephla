"""Single-plate supervised execution. No models, retries, recovery or approvals.

The console supplies a bounded catalog of existing executors. HumanConsole owns
all signatures. An interrupted/uncertain run retains the lab lease: a person
must reconcile it before creating another run. There is deliberately no resume
or clear-lock API exposed to Lacry in this first version.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import Path
import threading
import time

from .approval import approval_problem, attestation_problem, plan_hash
from .ledger import Ledger


@dataclass(frozen=True)
class Operation:
    machine: str
    name: str
    resources: tuple
    skill: str
    execute: object
    unattended_ok: bool = False


class SupervisedRun:
    """One signed plan, serialized across the whole lab, with durable intent."""
    def __init__(self, run, signer, operations, *, clock=time.time, notify=None, custody=None):
        self.run, self.signer, self.clock = run, signer, clock
        self.operations = {(op.machine, op.name): op for op in operations}
        self.notify = notify or (lambda event: None)
        self.custody = custody or (lambda run: None)
        self.cancel = threading.Event()
        self.lease = run.path.parent / '.supervised-lab-lease.json'
        self._guard = threading.Lock()
        self._plan_hash = plan_hash(run.plan)

    def stop(self):
        self.cancel.set()  # No instrument command. Existing executor observes it.

    def check(self):
        if self.cancel.is_set():
            raise RuntimeError('Operator stopped the experiment; no next step.')
        if plan_hash(self.run.plan) != self._plan_hash:
            raise RuntimeError('Approved experiment changed; no next step.')
        now = self.clock()
        window = self.run.plan['window']
        if not window['not_before'] <= now < window['expires_at']:
            raise RuntimeError('Experiment time window is not active.')
        grant = self.run.read_json('approval.json')
        if not self.signer.verify(grant) or grant.get('plan_hash') != self._plan_hash or now >= grant['expires_at']:
            raise RuntimeError('Experiment approval is missing, changed or expired.')
        # Execution mode is part of the signed plan. Lacry's approved plans
        # run autonomously; legacy callers may still explicitly attest presence.
        problem = None if self.run.plan.get('execution_mode')=='autonomous' else attestation_problem(self.run, self.signer, now)
        if problem:
            raise RuntimeError(problem)

    def _emit(self, status, **data):
        self.run.events.emit('status', status=status, data=data)
        self.run.write_json('experiment_status.json', dict(status=status, at=self.clock(), **data))
        # UI delivery is not part of the physical result. Evidence stays durable.
        try:
            self.notify(dict(status=status, **deepcopy(data)))
        except Exception as error:
            self.run.events.emit('anomaly', status='notification_failed', data=dict(error=str(error)))

    def validate(self):
        plan = self.run.plan
        if len(plan.get('plates', {})) != 1:
            raise ValueError('This version accepts exactly one registered plate.')
        if not plan.get('steps'):
            raise ValueError('No experiment steps.')
        window = plan.get('window', {})
        values = [window.get('not_before'), window.get('expires_at')]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values) or values[1] <= values[0]:
            raise ValueError('A finite bounded experiment time window is required.')
        ids = set()
        locations = dict(plan['plates'])
        for step in plan['steps']:
            if step['id'] in ids:
                raise ValueError('Duplicate experiment step ID.')
            ids.add(step['id'])
            op = self.operations.get((step['machine'], step['operation']))
            if op is None:
                raise ValueError('Operation is not bound to an accepted executor.')
            if list(op.resources) != step.get('resources'):
                raise ValueError('Operation resource contract changed.')
            transfer = step.get('transfer')
            if transfer:
                plate = transfer['plate']
                if locations.get(plate) != transfer['from'] or 'unknown' in (transfer['from'], transfer['to']):
                    raise ValueError('Experiment plate custody is inconsistent.')
                locations[plate] = transfer['to']

    def execute(self):
        if not self._guard.acquire(blocking=False):
            raise RuntimeError('Experiment executor is already running.')
        leased = False
        completed = []
        current = None
        dispatched = False
        try:
            self.validate()
            self.check()
            for step in self.run.plan['steps']:
                problem = approval_problem(self.run, self.signer, self.clock(), step['id'],
                                           step['machine'], step['operation'], step.get('params'))
                if problem:
                    raise RuntimeError(problem[1])
            if any(e['kind'] == 'command' for e in self.run.events.read()):
                raise RuntimeError('This experiment was already attempted; never redispatch it.')
            # Exclusive creation is cross-thread/process. Never reclaim by age.
            with self.lease.open('x', encoding='utf-8') as stream:
                json.dump(dict(run=str(self.run.path), plan_hash=self._plan_hash), stream)
                stream.flush()
                import os
                os.fsync(stream.fileno())
            leased = True
            ledger = Ledger(self.run)
            for step in self.run.plan['steps']:
                current, dispatched = step, False
                self.check()
                problem = approval_problem(self.run, self.signer, self.clock(), step['id'],
                                           step['machine'], step['operation'], step.get('params'))
                if problem:
                    raise RuntimeError(problem[1])
                transfer = step.get('transfer')
                if transfer and ledger.problem(transfer):
                    raise RuntimeError(ledger.problem(transfer))
                self._emit('running', step=step['id'], label=step['label'], completed=completed)
                started = self.clock()
                # fsynced intent BEFORE invoking any physical executor.
                self.run.events.emit('command', step=step['id'], machine=step['machine'],
                                     op=step['operation'], status='dispatch', data=step.get('params', {}))
                dispatched = True
                op = self.operations[(step['machine'], step['operation'])]
                result = op.execute(deepcopy(step), self)
                if not isinstance(result, dict) or result.get('ok') is not True:
                    raise RuntimeError('Operation did not verify completion: ' + str(result))
                self.run.events.emit('result', step=step['id'], status='completed', data=dict(
                    result=result, duration_s=self.clock()-started, estimate=step.get('estimate')))
                if transfer:
                    ledger.move(transfer, step['id'], self.clock())
                completed.append(step['id'])
                dispatched = False
                if transfer:
                    self.custody(self.run)
            self._emit('completed', completed=completed, plates=ledger.plates())
            self.lease.unlink()
            leased = False
            return dict(ok=True, status='completed', completed=completed, run_folder=str(self.run.path))
        except Exception as error:
            if current and dispatched and current.get('transfer'):
                Ledger(self.run).mark_unknown(current['transfer'], current['id'], self.clock())
            status = 'unknown' if dispatched else 'paused'
            self.run.events.emit('pause', step=current['id'] if current else None,
                                 status=status, data=dict(error=str(error), lease_retained=leased))
            if current and dispatched and current.get('transfer'):
                try:
                    self.custody(self.run)
                except Exception as custody_error:
                    self.run.events.emit('anomaly',status='registry_custody_unverified',data=dict(error=str(custody_error)))
            self._emit(status, error=str(error), completed=completed, lease_retained=leased,
                       step=current['id'] if current else None)
            return dict(ok=False, status=status, error=str(error), completed=completed)
        finally:
            self._guard.release()


def timing_samples(run_folders):
    """Only completed scheduler operations; no whole-run or inspection durations."""
    samples = {}
    for folder in run_folders:
        try:
            plan = json.loads((Path(folder)/'run.json').read_text(encoding='utf-8'))['plan']
            steps = {s['id']: s for s in plan['steps']}
            events = (Path(folder)/'events.jsonl').read_text(encoding='utf-8').splitlines()
            for line in events:
                e = json.loads(line)
                if e.get('kind') != 'result' or e.get('status') != 'completed':
                    continue
                duration = e.get('data', {}).get('duration_s')
                if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                    continue
                s = steps[e['step']]
                key = s.get('timing_key', s['machine']+':'+s['operation'])
                samples.setdefault(key, []).append(duration)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {key: dict(n=len(v), p50_s=sorted(v)[math.ceil(len(v)*.50)-1],
                      p95_s=sorted(v)[math.ceil(len(v)*.95)-1]) for key, v in samples.items()}


def timeline(steps, samples):
    cursor = 0.
    rows = []
    for step in steps:
        estimate = samples.get(step.get('timing_key', step['machine']+':'+step['operation']))
        rows.append(dict(id=step['id'], label=step['label'], machine=step['machine'],
                         start_s=cursor, estimate=estimate))
        cursor = cursor + estimate['p95_s'] if cursor is not None and estimate else None
    return dict(rows=rows, p95_total_s=cursor, estimate_complete=cursor is not None)
