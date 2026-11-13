"""Lacry's tools for the clean lab API (labfacade).

The model may read the machine manifests and live status, and propose ONE
operation as a plan. It cannot approve. When the researcher replies Yes to the
displayed plan, this module signs, on their behalf and in this process: the plan
approval, the E-stop attestation (when the operation needs it) and exactly the
confirmations the plan listed. The facade then runs the step once and logs it to
runs/<utc>_lacry-<operation>/. The signing key never reaches the model.

The run happens on its own thread, not the console runner, because the plate
workflow CLI refuses to start while the console runner is active.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time

from researcher_teaching import TeachingError, utc_now

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOOL_NAMES = ('lab_describe', 'lab_status', 'plan_lab_operation')
# Operations that carry the plate, and where it starts and ends. The ledger checks these.
PLATE_STEPS = {('bioyond_s4', 'run_plate_workflow'): ('bioyond deck', 'bioyond deck')}
PRESENCE = 'You are at the E-stop and stay there until this run ends.'
STOP_NOTE = 'Stop in the workspace asks the machine to stop after the current step. It is not an E-stop.'

RULES = '''
Clean lab API (lab_describe, lab_status, plan_lab_operation):
- These read the machine manifests and live machine status. plan_lab_operation
  proposes one manifest operation; this is NOT a limit on Lacry's other planners.
  For compound requests, use get_workflow_catalog and plan_workflow to compose
  existing workflows under one human confirmation. Use lab_describe when the researcher
  asks what a machine can do, and before planning an operation from it.
- Only operations that lab_describe shows as bound can run. Report anything else
  as not available yet; never substitute a different operation or tool.
- A status of unknown or error means stop and report it. Do not plan motion on it.
- plan_lab_operation shows a plan; it never starts anything. Only the
  researcher's Yes starts it, and you never confirm it. Report the run's result
  as given: completed, refused, waiting, paused, failed, unknown or
  completed_unverified. Never say an operation ran unless the result says completed.
'''


def _json(value, limit=12000):
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else json.dumps(dict(truncated=True, preview=text[:limit]))


class LabApi:
    def __init__(self, agent, facade=None, signer=None, runs=None, checkout=None):
        self.agent = agent
        self._facade, self._signer = facade, signer
        self.runs = Path(runs or ROOT / 'runs')
        self.checkout = Path(checkout or ROOT)
        self.lock = threading.Lock()
        self.job = None
        self.last = None
        self.aborting = False
        self.error = None

    # --- setup ---------------------------------------------------------------------------

    @property
    def available(self):
        return self._facade is not None or importlib.util.find_spec('labfacade') is not None

    def facade(self):
        if self._facade is None:
            from labfacade import Facade, Signer, load_manifests
            from labfacade.backends import BioyondConsoleBackend, HamiltonBackend, SquidBackend
            self._signer = Signer.from_file(self.runs / '.signing_key', create=True)
            squid = SquidBackend(reference=self.checkout / 'operator_ui' / 'squid_stage_reference.json')
            backends = dict(squid=squid, hamilton_prep=HamiltonBackend(),
                            bioyond_s4=BioyondConsoleBackend(checkout=self.checkout, squid=squid))
            self._facade = Facade.from_manifests(load_manifests(), backends, self._signer, self.runs)
        return self._facade

    @property
    def active(self):
        with self.lock:
            return bool(self.job and self.job['thread'].is_alive())

    def tools(self):
        if not self.available:
            return []
        try:
            if self._facade is not None:
                machines = self._facade.machines()
            else:                                   # listing reads manifests only; no key, no backends
                from labfacade import load_manifests
                machines = sorted(load_manifests())
        except Exception as error:
            self.error = f'{type(error).__name__}: {error}'
            return []
        machine = dict(type='string', enum=machines)
        return [
            dict(name='lab_describe',
                 description='Look up the clean lab API: the machines, their operations, risk, qualification, whether '
                             'each is wired (bound) in this build, parameters, limits, gates, known faults and recovery. '
                             'Reads the machine manifests only; moves nothing. Call without arguments for the list.',
                 input_schema=dict(type='object', properties=dict(machine=machine,
                                   operation=dict(type='string', maxLength=80)), additionalProperties=False)),
            dict(name='lab_status',
                 description='Live status of one machine through the clean lab API: busy, idle, error or unknown, '
                             'with a timestamp and the reason. Read-only.',
                 input_schema=dict(type='object', properties=dict(machine=machine), required=['machine'],
                                   additionalProperties=False)),
            dict(name='plan_lab_operation',
                 description='Propose ONE operation from the clean lab API as a plan for the researcher to confirm. '
                             'It is checked against the manifests first; problems (not wired, blocked, outside a '
                             'limit) come back instead of a plan. The plan lists every requirement the researcher '
                             'must confirm. Nothing moves until the researcher replies Yes, and you cannot confirm '
                             'it. A read-only operation runs at once and returns its result. Use lab_describe first '
                             'for the exact parameter names.',
                 input_schema=dict(type='object', properties=dict(
                     machine=machine, operation=dict(type='string', maxLength=80),
                     plate_id=dict(type='string', minLength=1, maxLength=512,
                                   description='Exact scanned plate ID. Required for run_plate_workflow; retrieve it from plate memory first.'),
                     params=dict(type='object', description='Only parameters the operation declares.'),
                     summary=dict(type='string', maxLength=200,
                                  description='One short sentence for the researcher.')),
                     required=['machine', 'operation'], additionalProperties=False)),
        ]

    def handles(self, name):
        return name in TOOL_NAMES

    # --- model tools ---------------------------------------------------------------------

    def run_tool(self, name, arguments):
        """(content, is_error) for one model tool call. Never starts motion."""
        try:
            if not self.available:
                raise TeachingError('The clean lab API is not installed in this console build.')
            facade = self.facade()
            if name == 'lab_describe':
                return _json(self.describe(arguments.get('machine'), arguments.get('operation'))), False
            if name == 'lab_status':
                status = facade.status(arguments['machine'])
                return _json(status), status.get('outcome') == 'refused'
            if name == 'plan_lab_operation':
                return _json(self.propose(arguments['machine'], arguments['operation'],
                                          arguments.get('params'), arguments.get('summary', ''), arguments.get('plate_id'))), False
            raise TeachingError(f'Unknown clean lab API tool {name}.')
        except TeachingError as error:
            return _json(dict(ok=False, refused=str(error))), True
        except Exception as error:
            return _json(dict(ok=False, refused=f'Clean lab API error: {type(error).__name__}: {error}')), True

    def describe(self, machine=None, operation=None):
        facade = self.facade()
        if machine is None:
            listing = []
            for name in facade.machines():
                d = facade.describe(name)
                listing.append(dict(machine=name, name=d.get('name'), manifest_valid=d.get('manifest_valid'),
                                    summary=d.get('summary'), operations=d.get('operations')))
            return dict(machines=listing)
        return facade.describe(machine, operation)

    def propose(self, machine, operation, params=None, summary='', plate_id=None):
        agent = self.agent
        if self.active:
            raise TeachingError('A clean lab API run is still in progress. Wait for it to finish.')
        runner = agent.get_runner()
        if runner.active or getattr(runner, 'reserved', False):
            raise TeachingError('Wait for the current lab task to finish.')
        with agent.lock:
            if agent.review:
                raise TeachingError('Finish the review waiting in the workspace first.')
        facade = self.facade()
        step = dict(id='s01', machine=machine, operation=operation, params=dict(params or {}))
        plates = {}
        plate_record = None
        registry = getattr(agent.memory, 'plates', None)
        if plate_id is not None or (machine, operation) in PLATE_STEPS:
            if not plate_id or registry is None:
                raise TeachingError('Choose the exact scanned plate ID from plate memory first. Nothing was planned or started.')
            try:
                plate_record = registry.get(plate_id)
            except ValueError as error:
                raise TeachingError(str(error)) from error
            plates = {plate_id: 'unknown'}
        if (machine, operation) in PLATE_STEPS:
            start, end = PLATE_STEPS[(machine, operation)]
            plates = {plate_id: start}
            step['transfer'] = {'plate': plate_id, 'from': start, 'to': end}
        lab_plan = dict(title=summary or f'{machine}: {operation}', plates=plates, steps=[step])
        problems = facade.validate_plan(lab_plan)
        if problems:
            raise TeachingError('Not possible as asked: ' + '; '.join(p['reason'] for p in problems) +
                                ' Nothing was planned or started.')
        detail = facade.describe(machine, operation)
        op = detail['operation']
        if op.get('risk') == 'read_only':
            result = facade.run_operation(machine, operation, step['params'])
            return dict(ok=result.get('outcome') == 'completed', read_only=True, result=result)

        from labfacade.runner import classify_gate, _check
        backend = facade.adapters[machine].backend
        qualification = detail['qualification']['status']
        presence = qualification != 'qualified'
        try:
            sensors = backend.sensors() or {}
        except Exception:
            sensors = {}
        confirmations, checked, blockers = [], [], []
        for gate in op.get('human_gate') or []:
            kind, key, text = classify_gate(gate)
            if kind == 'presence_attestation':
                presence = True
            elif kind == 'sensor_check' and sensors.get(key) is True:
                checked.append(text)
            elif kind == 'sensor_check' and sensors.get(key) is False:
                blockers.append(f'Sensor says no: {text}.')
            else:
                confirmations.append(text)
        for text in op.get('preconditions') or []:
            value = _check(backend, text, operation, step['params'])
            if value is False:
                blockers.append(f'Not met now: {text}.')
            elif value is None:
                confirmations.append(text)
            else:
                checked.append(text)
        if op.get('risk') == 'state_change':
            confirmations.append(f'confirm {operation}')
        status = facade.status(machine)
        if status['state'] != 'idle':
            blockers.append(f"{machine} is {status['state']}: {status['detail']}.")

        label = f'{machine}: {operation}' + (f' {step["params"]}' if step['params'] else '')
        if plate_record:
            label += ' | plate '+json.dumps(plate_id, ensure_ascii=False)
            confirmations.append('actual plate ID is '+json.dumps(plate_id, ensure_ascii=False))
        requirements = ([PRESENCE] if presence else []) + [f'Confirm: {t}.' for t in confirmations]
        requirements += [STOP_NOTE, f'Runs through the clean lab API ({qualification}) and is logged to runs/.']
        plan = dict(id=utc_now() + ':labapi', at=time.time(), source='chat', dispatch='labfacade',
                    summary=summary or label, labels=[label], steps=[dict(kind='labfacade', label=label)],
                    requirements=requirements, executable=not blockers, blockers=blockers,
                    lab_plan=lab_plan, confirmations=confirmations, presence=presence,
                    qualification=qualification, checked=checked, plate_record=plate_record)
        with agent.lock:
            agent.pending = plan
        agent.note(f'Clean lab API plan proposed: {label}; awaiting confirmation.')
        agent._announce_plan(plan)
        return dict(ok=True, awaiting_confirmation=bool(not blockers), plan=agent._plan_view(plan),
                    checked_automatically=checked)

    # --- after the researcher's Yes --------------------------------------------------------

    def start(self, plan):
        from labfacade import HumanConsole
        agent = self.agent
        if self.active:
            raise TeachingError('A clean lab API run is already in progress.')
        runner = agent.get_runner()
        if runner.active or getattr(runner, 'reserved', False):
            raise TeachingError('Another lab task is running. Nothing was started.')
        facade = self.facade()
        lab_plan = plan['lab_plan']
        problems = facade.validate_plan(lab_plan)
        if problems:
            raise TeachingError('The plan no longer passes its checks: ' + '; '.join(p['reason'] for p in problems))
        step = lab_plan['steps'][0]
        status = facade.status(step['machine'])
        if status['state'] != 'idle':
            raise TeachingError(f"{step['machine']} is {status['state']}: {status['detail']}. Nothing was started.")

        person = 'researcher via Lacry (' + plan.get('confirmation_source', 'workspace') + ')'
        plate_record = plan.get('plate_record')
        if plate_record:
            current = agent.memory.plates.get(plate_record['plate_id'])
            if current['revision'] != plate_record['revision']:
                raise TeachingError('Plate record changed after planning; prepare a fresh plan. Nothing was started.')
        run = facade.new_run(deepcopy(lab_plan), 'lacry-' + step['operation'])
        if plate_record:
            run.write_json('plate_identity.json', dict(plate=plate_record, source='persistent plate registry',
                                                      current_physical_identity_requires_confirmation=True))
        console = HumanConsole(run, self._signer)
        console.approve_plan(person)
        if plan.get('presence'):
            console.attest_presence(person)
        for text in plan.get('confirmations', []):
            console.confirm(step['id'], text, person)
        if plate_record:
            agent.memory.plates.record_run(plate_record['plate_id'], run.path.name, 'started', str(run.path))
        label = plan['labels'][0]
        with agent.lock:
            agent.pending = None
            agent.run_meta = dict(name=label, total_steps=1)
            agent.run_state = dict(active=True, step=label, done=[], ok=None, error='',
                                   message='Running through the clean lab API: ' + label + '.')
        thread = threading.Thread(target=self._run, args=(plan, run), daemon=True, name='lacry-lab-api')
        with self.lock:
            self.aborting = False
            self.job = dict(plan_id=plan['id'], label=label, machine=step['machine'], run=run,
                            thread=thread, started=time.time())
        thread.start()
        agent.note('Confirmed and started through the clean lab API: ' + label + '.')
        return dict(ok=True, run_folder=str(run.path),
                    message='Running through the clean lab API. Keep hands clear and watch the machines.')

    def _run(self, plan, run):
        agent, label = self.agent, plan['labels'][0]
        try:
            result = self.facade().run_step(run, 's01')
        except Exception as error:               # surfaced to the researcher, never retried
            result = dict(outcome='error', code='exception', reason=f'{type(error).__name__}: {error}')
        outcome = result.get('outcome')
        memory_error = None
        if plan.get('plate_record'):
            try:
                agent.memory.plates.record_run(plan['plate_record']['plate_id'], run.path.name,
                                               outcome or 'unknown', str(run.path))
            except Exception as error:
                memory_error = str(error)
                run.write_json('plate_memory_error.json', dict(error=memory_error, outcome=outcome))
        ok = outcome == 'completed'
        if ok:
            message = f'{label} completed through the clean lab API. Logged in {run.path.name}.'
        else:
            message = (f'{label} did not complete ({outcome}): {result.get("reason", "")} '
                       f'Nothing was retried. Logged in {run.path.name}.')
            if outcome in ('unknown', 'failed', 'completed_unverified', 'error'):
                message += ' Check the machine before planning anything else.'
        if memory_error:
            message += ' Plate memory update failed; inspect the saved run: '+memory_error
        with agent.lock:
            agent.run_state = dict(active=False, step=label, done=[label] if ok else [], ok=ok,
                                   error='' if ok else str(result.get('code') or outcome), message=message)
        with self.lock:
            self.last = dict(label=label, outcome=outcome, code=result.get('code'), run_folder=str(run.path),
                             finished=utc_now())
        agent.note(message)
        agent._say('lacry', message)

    def stop(self):
        """Stop the clean-API run, once. The backend's own stop may call back into Lacry's stop."""
        with self.lock:
            job, first = self.job, not self.aborting
            self.aborting = True
        if not job or not job['thread'].is_alive() or not first:
            return None
        result = self.facade().abort(job['machine'], job['run'], 's01')
        self.agent.note('Stop requested for the clean lab API run: ' + job['label'] + '.')
        return dict(ok=True, detail=result,
                    message='Stop requested. The step in progress may finish first; use the E-stop if you need it now.')

    def public(self):
        with self.lock:
            job = self.job
            return dict(available=self.available, error=self.error,
                        active=bool(job and job['thread'].is_alive()),
                        label=job['label'] if job else None,
                        run_folder=str(job['run'].path) if job else None,
                        last=deepcopy(self.last))
