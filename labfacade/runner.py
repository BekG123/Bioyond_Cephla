"""The one path every operation takes.

    approval -> qualification -> sensor checks -> attestation -> preconditions
             -> run -> postconditions -> log

Each stage writes an event. A refusal or a stop is a normal, logged result.
A timeout means the physical state is unknown: the step is logged, the status
is re-queried, the run pauses, and the command is never sent again.

Outcomes
    completed              sent, and the postconditions held
    refused                not allowed; nothing was sent
    waiting                nothing was sent; ask again when the reason is cleared
    paused                 nothing was sent; the run needs a person
    unknown                sent, no confirmed outcome; the run is paused
    failed                 sent, and it went wrong; the run is paused
    completed_unverified   sent and acknowledged, but a postcondition could not be checked; paused
"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time

from . import approval
from .events import NullEvents
from .manifest import RUNNABLE

DEFAULT_TIMEOUT_S = 60

# Free-text gates this layer recognizes. Anything else needs a fresh confirmation.
SENSOR_GATES = {
    'door closed': 'door_closed',
    'no object is held': 'nothing_held',
    'no plate held': 'nothing_held',
    'destination empty': 'destination_empty',
    'plate seated': 'plate_present',
    'plate loaded and supported': 'plate_present',
}


def classify_gate(gate):
    """(kind, sensor key or None, text). kind: sensor_check | presence_attestation | fresh_confirmation."""
    if isinstance(gate, dict):                      # the typed form proposed for the manifests
        kind = gate.get('type')
        text = gate.get('text') or gate.get('sensor') or str(kind)
        if kind == 'sensor_check' and gate.get('sensor'):
            return kind, gate['sensor'], text
        if kind == 'presence_attestation':
            return kind, None, text
        return 'fresh_confirmation', None, text
    text = str(gate)
    normal = ' '.join(text.lower().split())
    if 'e-stop' in normal:
        return 'presence_attestation', None, text
    if normal in SENSOR_GATES:
        return 'sensor_check', SENSOR_GATES[normal], text
    return 'fresh_confirmation', None, text


@dataclass
class Context:
    """What one call runs under. run is None only for a read made outside any run."""
    run: object = None
    signer: object = None
    clock: object = time.time
    step_id: str = None
    transfer: dict = None
    ledger: object = None
    events: object = field(default=None)

    def __post_init__(self):
        if self.events is None:
            self.events = self.run.events if self.run is not None else NullEvents()


def execute(adapter, name, params, ctx):
    from .dataset import StepDataset
    params = dict(params or {})
    m, backend = adapter.manifest, adapter.backend
    evidence = []
    dataset = StepDataset(ctx.run, m.id, ctx.step_id, backend, name) if ctx.run else None

    def ev(kind, status=None, data=None, artifacts=()):
        return ctx.events.emit(kind, machine=m.id, step=ctx.step_id, op=name, status=status,
                               data=data, artifacts=artifacts)

    def done(outcome, **extra):
        return dict(outcome=outcome, step_id=ctx.step_id, machine=m.id, operation=name,
                    evidence_paths=list(evidence), **extra)

    def refuse(code, reason, **detail):
        ev('result', 'refused', dict(code=code, reason=reason, **detail))
        return done('refused', code=code, reason=reason, detail=detail)

    def wait(code, reason, **detail):
        ev('gate', 'waiting', dict(code=code, reason=reason, **detail))
        return done('waiting', code=code, reason=reason, detail=detail)

    def stop(outcome, code, reason, **detail):
        ev('anomaly', code, dict(reason=reason, **detail))
        ev('pause', code, dict(reason=reason))
        return done(outcome, code=code, reason=reason, detail=detail)

    # --- what is being asked ---------------------------------------------------------
    if not m.valid:
        return refuse('manifest_invalid', f'{m.path.name} does not validate, so nothing on it may run.',
                      errors=m.errors[:5])
    op = m.operation(name)
    if op is None:
        return refuse('unknown_operation', f"'{name}' is not an operation of {m.id}.")
    problem = m.check_params(op, params)
    if problem:
        return refuse(problem.code, problem.reason, **problem.detail)
    if not adapter._bound(name):
        return refuse('not_bound', f"'{name}' is in the manifest but is not wired to {m.id} in this build.")
    risk = op.get('risk')
    timeout_s = op.get('timeout_s', DEFAULT_TIMEOUT_S)
    if hasattr(backend, 'timeout_s'):               # a backend may size the timeout from the parameters
        timeout_s = backend.timeout_s(name, params) or timeout_s

    def progress(line):
        ev('status', 'progress', dataset.progress(line) if dataset else dict(phase='progress', line=line))

    if risk == 'read_only':
        if dataset:
            dataset.before()
        ev('command', 'sent', dict(params=params))
        outcome, payload = _call(backend, name, params, timeout_s)
        if dataset:
            evidence.extend(dataset.after())
        if outcome != 'ok':
            ev('result', 'unknown', dict(code=outcome, reason=payload))
            return done('unknown', code=outcome, reason=payload)
        ev('result', 'completed', dict(result=payload))
        return done('completed', result=payload)

    # --- approval ----------------------------------------------------------------------
    if ctx.run is None or ctx.signer is None or ctx.step_id is None:
        return refuse('no_plan_step', 'Motion and state changes run only as a step of an approved plan.')
    now = ctx.clock()
    paused = approval.open_pause(ctx.run, ctx.signer)
    if paused:
        return refuse('run_paused', 'The run is paused and needs a person to resume it.',
                      pause_seq=paused['seq'], pause_reason=paused['data'].get('reason'))
    if any(e['kind'] == 'command' and e['step'] == ctx.step_id and e['op'] != 'abort' for e in ctx.events.read()):
        return refuse('already_attempted', 'This step was already sent once. It is never sent again.')
    problem = approval.approval_problem(ctx.run, ctx.signer, now, ctx.step_id, m.id, name, params)
    if problem:
        return refuse(*problem)

    # --- qualification -----------------------------------------------------------------
    status, entry = m.qualification(op)
    if status not in RUNNABLE:
        if not approval.overridden(ctx.run, ctx.signer, ctx.step_id):
            return refuse('not_qualified', f"'{name}' is {status}. A person must override it explicitly.",
                          qualification=status, blocker=entry.get('blocker'))
        ev('approval', 'override_used', dict(qualification=status))
    needs_presence = status != 'qualified'

    # --- sensor checks, then attestation ---------------------------------------------
    try:
        sensors = backend.sensors() or {}
    except Exception as error:
        sensors = {}
        ev('anomaly', 'sensors_unreadable', dict(error=str(error)))
    ask = []
    for gate in op.get('human_gate') or []:
        kind, key, text = classify_gate(gate)
        if kind == 'presence_attestation':
            needs_presence = True
        elif kind == 'sensor_check' and sensors.get(key) is True:
            ev('gate', 'sensor_ok', dict(gate=text, sensor=key))
        elif kind == 'sensor_check' and sensors.get(key) is False:
            return wait('sensor_check_failed', f"Sensor '{key}' says no: {text}.", gate=text, sensor=key)
        else:
            ask.append(text)                        # no sensor can answer, so a person must
    if risk == 'state_change':
        ask.append(f'confirm {name}')               # never covered by the run-level attestation
    if needs_presence:
        problem = approval.attestation_problem(ctx.run, ctx.signer, now)
        if problem:
            ev('pause', 'attestation', dict(reason=problem))
            return done('paused', code='attestation', reason=problem)
        ev('gate', 'presence_ok')

    # --- preconditions -----------------------------------------------------------------
    before = adapter.status()
    ev('status', before['state'], dict(before, phase='before'))
    if before['state'] in ('unknown', 'error'):
        return stop('paused', 'state_' + before['state'], f"{m.id} is {before['state']}: {before['detail']}")
    if before['state'] == 'busy':
        return wait('machine_busy', f'{m.id} is busy: {before["detail"]}')
    for text in op.get('preconditions') or []:
        value = _check(backend, text, name, params)
        if value is False:
            return wait('precondition_not_met', f'Precondition not met: {text}.', precondition=text)
        if value is None:
            ask.append(text)
    missing = [text for text in ask if not approval.confirmed(ctx.run, ctx.signer, now, ctx.step_id, text)]
    if missing:
        return wait('needs_confirmation', 'A person must confirm these before the step runs.', confirm=missing)
    for text in ask:
        ev('gate', 'confirmed', dict(gate=text))
    if ctx.transfer:
        problem = ctx.ledger.problem(ctx.transfer)
        if problem:
            return stop('paused', 'ledger_mismatch', problem, transfer=ctx.transfer)

    # --- run ----------------------------------------------------------------------------
    if dataset:
        dataset.before()
    ev('command', 'sent', dict(params=params, timeout_s=timeout_s))   # the durable 'sent once' marker
    outcome, payload = _call(backend, name, params, timeout_s, progress)
    if dataset:
        evidence.extend(dataset.after())
    if outcome != 'ok':
        requery = adapter.status()
        ev('status', requery['state'], dict(requery, phase='requery'))
        if ctx.transfer:
            ctx.ledger.mark_unknown(ctx.transfer, ctx.step_id, ctx.clock())
        if outcome == 'timeout':
            return stop('unknown', 'timeout',
                        f'No confirmed outcome within {timeout_s} s. Physical state is unknown; not resent.',
                        detail=payload, status_after=requery)
        return stop('failed', 'error', f'The operation failed: {payload}', status_after=requery)

    # --- postconditions ----------------------------------------------------------------
    after = adapter.status()
    ev('status', after['state'], dict(after, phase='after'))
    checks = {text: _check(backend, text, name, params) for text in op.get('postconditions') or []}
    failed = [text for text, value in checks.items() if value is False]
    unverified = [text for text, value in checks.items() if value is None]
    if after['state'] in ('unknown', 'error') or failed:
        if ctx.transfer:
            ctx.ledger.mark_unknown(ctx.transfer, ctx.step_id, ctx.clock())
        reason = (f'Postcondition failed: {"; ".join(failed)}.' if failed
                  else f"{m.id} is {after['state']} after the step: {after['detail']}")
        return stop('failed', 'postcondition_failed', reason, failed=failed, status_after=after, result=payload)
    if unverified:
        if ctx.transfer:
            ctx.ledger.mark_unknown(ctx.transfer, ctx.step_id, ctx.clock())
        return stop('completed_unverified', 'postcondition_unverified',
                    'The machine acknowledged the step, but these could not be checked: ' + '; '.join(unverified),
                    unverified=unverified, result=payload)
    if ctx.transfer:
        ctx.ledger.move(ctx.transfer, ctx.step_id, ctx.clock())
    ev('result', 'completed', dict(result=payload, postconditions=list(checks)))
    return done('completed', result=payload)


def _check(backend, text, name=None, params=None):
    try:
        if getattr(backend, 'context_checks', False):   # some checks depend on the parameters
            value = backend.check(text, name=name, params=params)
        else:
            value = backend.check(text)
    except Exception:
        return None
    return value if value in (True, False) else None


def _call(backend, name, params, timeout_s, progress=None):
    """('ok', result) | ('timeout', why) | ('error', why). Never retries."""
    box = {}

    def work():
        try:
            if progress and getattr(backend, 'accepts_progress', False):
                box['result'] = backend.run(name, params, timeout_s, progress=progress)
            else:
                box['result'] = backend.run(name, params, timeout_s)
        except TimeoutError as error:
            box['timeout'] = str(error) or 'backend reported a timeout'
        except Exception as error:
            box['error'] = f'{type(error).__name__}: {error}'

    thread = threading.Thread(target=work, daemon=True, name=f'labfacade-{name}')
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        return 'timeout', f'no reply within {timeout_s} s'
    if 'timeout' in box:
        return 'timeout', box['timeout']
    if 'error' in box:
        return 'error', box['error']
    return 'ok', box.get('result')
