# Hotel registration and instrument execution

Lacry's `plan_workflow` now binds the accepted Cellvis P24-1.5H-N
slot-1 retrieval and barcode adapter to the existing instrument tools.
`plan_plate_transfer` remains handling-only; it does not start imaging or pipetting.

Supported instrument chains start with slot 1 retrieval, HOME reseating and
fresh barcode registration. They then run Hamilton, Squid, or Hamilton followed
by Squid. Each station receives the plate from HOME, releases it, and the empty
arm returns HOME before instrument work. Retrieval waits for that exact job's
successful completion. Squid additionally restores and verifies its loading
reference before retrieval. The final plate location is HOME.

The router preserves requested operations and image counts. A Hamilton recipe
is required only when Hamilton liquid handling is requested. It must be
commissioned for this Cellvis profile at site 4; protocol hashes, inventory and
fresh job identity are checked by `HamiltonPrep`. There is no automatic protocol
creation, calibration or substitution of a mock method. Squid uses
`SquidExecution.prepare/start/wait/restore_loading/observe` and its immutable
settings snapshot. `image_count` means total images, not transfer cycles. A
count differing from the selected snapshot blocks planning with an actionable
settings message. No wells, channels, exposure or autofocus are guessed.

Example `plan_workflow` arguments for the researcher's imaging request:

```json
{
  "operations": ["retrieve_hotel", "register_plate", "deliver_squid",
                 "squid_image", "retrieve_squid", "return_HOME"],
  "plate_profile": "Cellvis P24-1.5H-N",
  "source_slot": 1,
  "image_count": 5
}
```

To add Hamilton before Squid, insert `hamilton_protocol` after `register_plate`
and supply `recipe` with a commissioned recipe key. Explicit
`deliver_hamilton` / `hamilton_protocol` / `retrieve_hamilton` is also accepted.
One hotel chain runs once; requests for repeated hotel pickups are not silently
converted into repeated scans or acquisitions.

The researcher UI shows all steps, exact Hamilton recipe/hash and Squid
settings/count before one human Yes. The approved window includes instrument
timeouts, capped at four hours. The existing human-only **Still supervising**
button renews presence for five minutes. Lapsed presence stops the chain;
heartbeats cannot resume an expired/stopped run. No model tool approves or
renews supervision.

Implementation reuses accepted `cellvis24_workflow` delivery and retrieval
phases split at `Empty HOME clearance`. It adds no motion coordinates or robot
connection. Dispatch stays inside the Flask console's shared runner. Barcode
receipt hashes, fresh HOME release evidence, profile bindings and single-use
source checks remain required. Instrument phase receipts carry plate custody,
exact job tickets, a plan hash, run identity and a predecessor checksum. Each
phase is exclusively claimed before sending commands. Faults, timeout, changed
settings/identity or unknown results retain the composed-transfer hold and stop
the rest of the chain without replay.

Offline tests cover both instrument chains, unchanged accepted motion slices,
read-only previews, source identity, image counts, missing recipes, exact-job
checks, loading failures, single-use claims, changed receipts, and supervision
expiry. Passing these tests is not an operator acceptance of a new physical run.
