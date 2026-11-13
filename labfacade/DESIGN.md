# Approval model

## The idea

A researcher approves an execution plan once. The run then proceeds without further
prompts unless something happens that a person has to decide. Approval is a bounded
authorization, not a switch.

## What one approval covers

`approval.json` holds the plan hash, the approver, the time, an expiry, and the exact
list of `(step, machine, operation, params)` it allows. Before any motion or state change
the runner checks, in code:

1. the record exists, is signed by the console's key, and belongs to this run;
2. it has not expired;
3. the plan on disk still hashes to the approved hash;
4. this call matches one allowed entry exactly.

Any edit to the plan changes the hash, so the approval stops applying.

## Who can grant

Only `HumanConsole`. It signs every record (HMAC-SHA256). `Facade` holds a verifier and
exposes no granting method. This separates the two roles in code, and a test checks the
facade's surface. It is **not** a security boundary against a process that can read the
key file or import `HumanConsole` itself: in production the console must run in the UI
process, with the key somewhere the agent's tools cannot read.

## Autonomy follows qualification

| Manifest status | What is needed |
| --- | --- |
| `qualified` | plan approval |
| `supervised_only` | plan approval and a live presence attestation |
| `blocked`, `untested`, `needs_review` | refused; a person may override one step, and the override is logged |

## Presence attestation

At approval a person attests they are at the E-stop for this run. The record has an
expiry and a heartbeat interval. If the heartbeat lapses, the next supervised step does
not start: the run pauses. A heartbeat alone does not un-pause it; a person resumes.

## Fewer questions, not zero

- A gate a sensor can answer is answered by the sensor.
- A gate about the E-stop is answered by the attestation.
- Any other gate, and any precondition the backend cannot evaluate, needs a fresh
  confirmation for that step. It expires after two minutes.
- `state_change` operations (enable, clear errors, start a program) always need a fresh
  confirmation of their own.

With the manifests as they are today, most gates are free text, so most motion steps will
still ask a person. `proposals/typed_gates.md` is the change that reduces that.

## When the run pauses

Unknown or error state, a timeout, an error, a failed or uncheckable postcondition, a
ledger mismatch, a missing or lapsed attestation. A pause is an event; while it is open
every motion step is refused with `run_paused`. Resuming needs `HumanConsole.resume`.

## Never twice

The `command` event is written before the command is sent. A step with a `command`
event is never sent again, including after a crash or a resume, because the check reads
the event log. A timed-out transfer also sets the plate's ledger location to `unknown`.

## Assumptions to confirm

- Qualification keys equal operation names. Today several motion operations have no
  matching key (for example `run_station_job`, `home_stage`), so they are `untested`.
- A scalar limit is a maximum magnitude.
- Reads need no approval.
- A resumed run never re-sends the step that stopped it.
