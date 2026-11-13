# labfacade

One interface for the Bioyond S4 arm, the Hamilton Prep and the Squid microscope, driven
by the manifests in `machines/`. An agent plans and asks; this layer decides what may run,
runs it once, checks the result, and writes everything to one run folder.

**Status of this build:** the whole stack is tested against fake machines.

- **Squid:** status and reads are wired, plus one motion, `return_to_loading`. Its
  move ran once on the live Squid on 2026-11-11, supervised, with no plate on the stage:
  Z went from 0.100 to the 0.064 mm target and the position was verified (run
  `20261111T142841Z_squid-return-to-loading`). One run is not a qualification. It is
  also tested against a local fake Squid server. Supervised check:
  `py -m labfacade.live_squid_return` (read-only by default).
- **Bioyond:** status reads, plus `run_plate_workflow`, which launches the existing
  `operator_ui/run_plate_workflow.py` unchanged in the folder the console runs from and
  logs each of its output lines as an event. The read-only preflight and workflow preview ran against the live console on 2026-11-11. One full calibration/Hamilton/Squid handling cycle completed through this layer on
  2026-11-11 (`20261111T145950Z_plate-workflow`), with operator assessment pending.
  The newer dataset integrations are tested offline only. Supervised check: `py -m labfacade.live_plate_workflow` (read-only by
  default). Every other arm operation returns `not_bound`.
- **Hamilton:** status read only, **not run against the hardware**. Every motion or
  state-change operation returns `not_bound`.

## Quickstart (no hardware)

```
py -m pytest labfacade/tests -q
py -m labfacade.replay_fake_plan
```

The replay approves one plan, runs it on three fake machines, hits an injected fault at
step 3, pauses, and prints the run folder.

## Lacry

Lacry reaches this layer through `operator_ui/lacry_facade.py`, as three extra tools:
`lab_describe` (manifests), `lab_status` (live state) and `plan_lab_operation` (one
operation, checked with `validate_plan` and shown as a normal Lacry plan). The model
cannot approve. When the researcher replies Yes, the console process signs the plan
approval, the E-stop attestation and exactly the listed confirmations, then the facade
runs the step once on its own thread and logs it to `runs/<utc>_lacry-<operation>/`.
One operation per plan in this build. Stop in the workspace calls the facade's abort.
The tools appear only when `labfacade` is importable, so a console started from a
checkout without it is unchanged. Tested offline (`operator_ui/tests/test_lacry_lab_api.py`).

## The two objects

| Object | Who holds it | What it can do |
| --- | --- | --- |
| `Facade` | the agent | `status`, `describe`, `validate_plan`, `new_run`, `run_step`, `run_operation`, `abort` |
| `HumanConsole` | the UI, for a person | `approve_plan`, `attest_presence`, `heartbeat`, `confirm`, `override`, `resume` |

The facade has no method that grants anything, and no call takes an `approved` argument.
What a person grants is signed with a key the console holds; the facade only verifies it.

```python
from labfacade import Facade, HumanConsole, Signer, load_manifests

manifests = load_manifests()                       # machines/*.yaml, validated; invalid ones refuse everything
facade = Facade.from_manifests(manifests, backends, signer, 'runs')

facade.describe('squid')                           # operations, risk, qualification, wired or not
facade.validate_plan(plan)                         # problems to show a person before they approve
run = facade.new_run(plan, 'plate-to-squid')       # creates runs/<utc>_plate-to-squid/

person = HumanConsole(run, signer)                 # UI side only
person.approve_plan('bek')                         # the one approval
person.attest_presence('bek', heartbeat_s=300)     # "I am at the E-stop for this run"

facade.run_step(run, 's01')                        # -> {outcome, step_id, evidence_paths, ...}
```

A plan is plain data:

```python
plan = {'title': '...', 'plates': {'P1': 'gripper'}, 'steps': [
    {'id': 's01', 'machine': 'squid', 'operation': 'return_to_loading', 'params': {}},
    {'id': 's02', 'machine': 'bioyond_s4', 'operation': 'place_plate', 'params': {'station': 'squid'},
     'transfer': {'plate': 'P1', 'from': 'gripper', 'to': 'squid stage'}}]}
```

## What happens to one step

approval → qualification → sensor checks → attestation → preconditions → run →
postconditions → log. Each stage writes an event.

| Outcome | Meaning | Was a command sent? |
| --- | --- | --- |
| `completed` | postconditions held | yes |
| `refused` | not allowed (`code` says why) | no |
| `waiting` | a sensor, precondition or person's answer is missing; ask again | no |
| `paused` | the run needs a person (`HumanConsole.resume`) | no |
| `unknown` | timeout; physical state unknown; run paused | yes, once |
| `failed` | error or failed postcondition; run paused | yes, once |
| `completed_unverified` | acknowledged, but a postcondition could not be checked; run paused | yes, once |

A step is sent at most once. After a timeout it is refused as `already_attempted`, even
after the run is resumed. Recovery is a new plan and a new approval.

## The run folder

```
runs/<utc>_<slug>/
  run.json          plan, versions, manifest hashes
  events.jsonl      append-only, one JSON object per line (schemas/event.schema.json)
  ledger.json       where each plate is
  approval.json  attestation.json  human.jsonl     signed, written only by HumanConsole
  frames/           <step>_before.png, <step>_after.png
  squid/ hamilton_prep/ bioyond_s4/                images and raw journals (run.collect)
```

Arrays and images stay in their own files (OME-Zarr from Squid, PNG frames). Facts go in
`events.jsonl`, and each event points at its files by relative path and SHA-256.
`facade.squid_saving_format(software_dir, run)` reports what Squid is set to write and
logs a warning when it is not `ZARR_V3`.

## Rules this layer applies to the manifests

- A manifest that fails `manifest.schema.json` is loaded but refuses every operation.
- `read_only` operations need no approval and may run outside a run.
- `motion` and `state_change` run only as a step of an approved plan.
- Qualification is looked up **by operation name**. No entry means `untested`.
  `qualified` runs under plan approval; `supervised_only` also needs a live attestation;
  anything else is refused unless a person overrides that step.
- A parameter must be declared under the operation's `parameters`. If a limit has the
  same name, a number is a maximum magnitude and `[lo, hi]` is a range.
- Gates: text containing "E-stop" is covered by the attestation; a few known phrases map
  to sensors (`runner.SENSOR_GATES`); every other gate needs a fresh confirmation.
- A precondition or postcondition the backend cannot evaluate is never assumed true: the
  precondition becomes a question for a person, the postcondition makes the step
  `completed_unverified`.

## Files

`manifest.py` loader · `approval.py` signing and checks · `runner.py` the step path ·
`adapters.py` the four calls · `facade.py` agent entry point · `events.py` run folder and
log · `ledger.py` plates · `fakes.py` fake machine · `backends.py` real reads ·
`squid_format.py` saving-format check · `proposals/` changes for the owner to apply.

## Dataset integration (0.2.0)

See [DATASET.md](DATASET.md) for the exact directory contract, automatic collection,
frame provenance, completed-acquisition handoff, OME validation scope, and remaining
hardware verification. The event schema is unchanged. Machine folder aliases are now
`bioyond/`, `hamilton/`, `squid/`, with unique step-scoped artifact paths.

Verify a dataset offline:

```powershell
py -B -m labfacade.verify_dataset path/to/run
```

For stopped/completed plate runs, `py -B -m labfacade.reconcile_dataset path/to/run
--checkout path/to/execution-checkout` backfills referenced receipts from local files
and reviews frame quality. It preserves historical events and artifacts and archives
the prior completeness summary; see [DATASET.md](DATASET.md) for its single-writer
requirement and validation scope.
