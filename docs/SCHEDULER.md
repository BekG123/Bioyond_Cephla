# First supervised experiment version

Scope narrowed by the operator on 2026-11-12: one registered Cellvis
P24-1.5H-N plate, sequential Hamilton/Squid work, one displayed plan and one
human approval. Multi-plate scheduling, hotel buffering, unattended execution
and general protocol authoring are deferred.

The integration is prepared in `experiment/scheduler-20261112`, based on
`clean-api`, with current runtime files copied from the operator checkout.
Neither original checkout is changed. The eight committed clean-api changes
are ahead of main's committed HEAD; main's working files contain newer accepted
routes, Sonnet support and plate workflows. Copied pre-existing work remains
uncommitted; new scheduler work is committed separately. Do not push or replace
the live checkout without reviewing that integration baseline.

## Researcher flow

1. Establish calibration and barcode registration using the existing accepted
   workflows. This first version starts from a fresh, unused completed HOME
   release receipt. It does not recalibrate or rescan automatically.
2. Ask Lacry: “Plan one supervised experiment for plate SU-PRKL-P-2611-0001,
   using commissioned Hamilton recipe [name] and current Squid imaging settings.”
3. Lacry reads the registered profile, current recipe/hash/inventory, imaging
   selection and accepted handling evidence. Missing facts or uncommissioned
   recipes block planning before the arm moves.
4. Review the plate ID, complete cycle count, protocol/hash, imaging snapshot,
   sequence, timing estimates and setup requirements. Reply Yes or press the
   existing Yes button. No additional per-cycle approval is created.
5. Stay at the E-stop. Press **Still supervising** within five minutes to renew
   presence. The browser never sends that heartbeat automatically.
6. Stop prevents further steps and invokes the existing runner's stop behavior.
   Use the E-stop for immediate stopping. A timeout or uncertain result retains
   the experiment lease and stops. There is no automatic restart or retry.

Each cycle is HOME → Hamilton delivery → run/wait for the exact Hamilton job →
Hamilton retrieval/HOME → prepare Squid loading → Squid delivery → image/wait for
the exact acquisition and restore loading → Squid retrieval/HOME. The plate is
released in HOME between stations. Arm handling never overlaps instrument work.

## Implementation

- `labfacade/supervised.py`: deterministic serial runner; signed plan and presence
  verification; a whole-lab exclusive lease; durable command intent before
  dispatch; existing ledger; completion-only transitions; actual durations.
- `operator_ui/supervised_experiment.py`: adapter to existing compiled Cellvis
  routes and existing HamiltonPrep/SquidExecution exact-job monitors. The split
  is at the accepted **Empty HOME clearance** checkpoint. No new motion points,
  speeds, gripping targets, or safety tolerances are introduced.
- `operator_ui/lacry_experiment.py`: proposals, experiment records, human-only
  start and presence renewal; tools cannot sign, attest, resume or execute.
- `operator_ui/static/supervised_experiment.*`: plan timeline, recipe/imaging
  details, current result and manual supervision renewal beside Lacry chat.

All five operation contracts reserve arm, HOME, Hamilton site 4 and Squid stage
for the entire experiment; all have `unattended_ok=False`. Delivery/retrieval
reuse `cellvis24-scan-station-cycle-v1`'s handling contract and `opposite3` route.
Hamilton protocol work requires an existing reviewed recipe and exact native
completion; Squid work requires a bound settings/reference snapshot and exact
acquisition completion. The new orchestration is offline-tested, not itself an
operator-accepted physical workflow.

The adapter remains inside the existing Flask console and uses its service and
runner; it never opens a second robot SDK connection. Preview skips the existing
Lua capability handshake (which writes registers); approved execution retains
that handshake and all original route, source-age and single-use checks.

## Records and timing

`runs/experiments/<id>/` contains the approved immutable plan, signed grant and
presence, `events.jsonl`, `ledger.json`, step receipts, exact instrument tickets,
imaging output links and `experiment_status.json`. Hardware completion is not
an operator's visual acceptance. The ledger and registry are updated after each
verified transfer; an uncertain transfer marks custody unknown. Registry updates
use revision checks and `verified_workflow_receipt` evidence, never a fabricated
researcher report. External metadata changes stop the experiment.

Timing uses p50/p95 of completed operation results with matching operation and
protocol/settings hashes. Unmeasured durations are explicitly unknown. Inspection
pauses and failed whole-run durations are not represented as travel estimates.
The first version does not predict overnight fit.

An interrupted run retains `.supervised-lab-lease.json`; it is never stolen by
age. A person must review the event log, machine state and plate custody before
any recovery. No agent tool clears the lease or resumes a physical step.

## Offline checks

`python -m labfacade.demo_supervised` runs only fakes with an injected cycle-2
timeout. The fake human signature is test data, never live permission.
Run the existing suites plus `test_supervised.py` and
`test_supervised_experiment.py` with hardware networking disabled.

Live read-only check on 2026-11-12: the console reported the arm disconnected;
Hamilton reported Idle and returned eight catalog entries; zero commissioned
recipes were configured. The registered plate has successful scans, but its
metadata still needs an explicit Cellvis model declaration. These are blockers
for a physical experiment, not reasons to relax validation.

Before activation: review baseline integration, prepare the console environment
with labfacade dependencies, choose/verify the Cellvis Hamilton protocol and
native simulation, commission its hash and inventory, and authorize a supervised
physical trial. No console reload or real run is part of the offline build.
