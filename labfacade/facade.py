"""What the agent is given. It can ask, plan and run approved steps. It cannot approve."""
from __future__ import annotations

import time

from .adapters import MachineAdapter
from .events import RunFolder
from .ledger import Ledger, LOCATIONS
from .manifest import RUNNABLE
from .runner import Context
from . import squid_format


class Facade:
    def __init__(self, adapters, signer, runs_root, clock=time.time):
        self.adapters = {a.id: a for a in adapters}
        self._signer, self.runs_root, self.clock = signer, runs_root, clock

    @classmethod
    def from_manifests(cls, manifests, backends, signer, runs_root, clock=time.time, stale_after_s=10):
        """One adapter per manifest that has a backend."""
        return cls([MachineAdapter(manifests[name], backend, clock, stale_after_s)
                    for name, backend in backends.items()], signer, runs_root, clock)

    def machines(self):
        return sorted(self.adapters)

    def status(self, machine):
        adapter = self.adapters.get(machine)
        return adapter.status() if adapter else self._no_machine(machine)

    def describe(self, machine, operation=None):
        adapter = self.adapters.get(machine)
        return adapter.describe(operation) if adapter else self._no_machine(machine)

    def validate_plan(self, plan):
        """Problems a person should see before approving. Empty means the plan can run as written."""
        problems = []
        steps = plan.get('steps') if isinstance(plan, dict) else None
        if not isinstance(steps, list) or not steps:
            return [dict(step=None, code='no_steps', reason='A plan needs a list of steps.')]
        ids = [s.get('id') for s in steps if isinstance(s, dict)]
        if len(ids) != len(steps) or len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
            problems.append(dict(step=None, code='bad_step_ids', reason='Every step needs a unique id.'))
        for plate, location in (plan.get('plates') or {}).items():
            if location not in LOCATIONS:
                problems.append(dict(step=None, code='bad_location', reason=f"Plate '{plate}' is at '{location}'."))
        for step in steps:
            if not isinstance(step, dict):
                continue
            def add(code, reason, **detail):
                problems.append(dict(step=step.get('id'), code=code, reason=reason, **detail))
            adapter = self.adapters.get(step.get('machine'))
            if adapter is None:
                add('unknown_machine', f"No machine '{step.get('machine')}'.")
                continue
            m = adapter.manifest
            if not m.valid:
                add('manifest_invalid', f'{m.path.name} does not validate.')
                continue
            op = m.operation(step.get('operation'))
            if op is None:
                add('unknown_operation', f"'{step.get('operation')}' is not an operation of {m.id}.")
                continue
            problem = m.check_params(op, step.get('params'))
            if problem:
                add(problem.code, problem.reason, **problem.detail)
            status, entry = m.qualification(op)
            if status not in RUNNABLE + ('not_required',):
                add('not_qualified', f"'{op['name']}' is {status}.", blocker=entry.get('blocker'))
            if not adapter._bound(op['name']):
                add('not_bound', f"'{op['name']}' is not wired in this build.")
        return problems

    def new_run(self, plan, slug):
        """Create the run folder for a plan. It still needs a person's approval before anything moves."""
        return RunFolder.create(self.runs_root, slug, plan,
                                {a.id: a.manifest for a in self.adapters.values()}, self.clock)

    def run_step(self, run, step_id):
        step = next((s for s in run.plan.get('steps', []) if s.get('id') == step_id), None)
        if step is None:
            run.events.emit('result', step=step_id, status='refused',
                            data=dict(code='unknown_step', reason=f"No step '{step_id}' in the plan."))
            return dict(outcome='refused', step_id=step_id, code='unknown_step',
                        reason=f"No step '{step_id}' in the plan.", evidence_paths=[])
        return self.run_operation(step['machine'], step['operation'], step.get('params'), run, step_id)

    def run_operation(self, machine, name, params=None, run=None, step_id=None):
        adapter = self.adapters.get(machine)
        if adapter is None:
            return self._no_machine(machine)
        step = None
        if run is not None and step_id is not None:
            step = next((s for s in run.plan.get('steps', []) if s.get('id') == step_id), None)
        context = Context(run=run, signer=self._signer, clock=self.clock, step_id=step_id,
                          transfer=(step or {}).get('transfer'), ledger=Ledger(run) if run is not None else None)
        return adapter.run_operation(name, params, context)

    def abort(self, machine, run=None, step_id=None):
        adapter = self.adapters.get(machine)
        if adapter is None:
            return self._no_machine(machine)
        return adapter.abort(Context(run=run, signer=self._signer, clock=self.clock, step_id=step_id))

    def squid_saving_format(self, software_dir, run=None):
        """Report what Squid is configured to write, and log a warning when it is not OME-Zarr."""
        report = squid_format.configured_saving_format(software_dir)
        if run is not None:
            run.events.emit('status' if report['zarr'] else 'anomaly', machine='squid',
                            status='saving_format', data=report)
        return report

    def collect_acquisition(self, run, step_id, receipt, expected_run_id, output_roots):
        """Read-only handoff of a completed Squid acquisition into this run."""
        from .dataset import collect_acquisition
        try:
            return collect_acquisition(run, step_id, receipt, expected_run_id, output_roots)
        except Exception as error:
            run.events.emit('anomaly', machine='squid', step=step_id, op='collect_acquisition',
                            status='imaging_dataset_rejected', data=dict(receipt=str(receipt), error=str(error)))
            raise

    def _no_machine(self, machine):
        return dict(outcome='refused', code='unknown_machine', reason=f"No machine '{machine}'.",
                    machines=self.machines(), evidence_paths=[])
