# Hamilton API access in Lacry

## Single-approval simulation and execution

`plan_hamilton_experiment(draft_id, plate_id)` is the preferred path for a fully
specified experiment on a plate already at Hamilton site 4. One human approval
covers native protocol creation if necessary, native simulation and conditional
physical execution. Successful exact-job simulation advances directly to the
live run: no separate commissioning, second approval, or physical-validation
trial is required. `draft_protocol` and `adopt_hamilton_protocol` feed this tool.

The execution binding is single-use and stored in the draft record; it does not
create or modify a globally commissioned recipe. Existing recipe-based workflows
remain available. Missing experimental inputs are still collected before the
initial plan. Changed hashes/inventory/session, stale or failed simulation,
Stop and timeout prevent physical dispatch. Physical completion is checked by
the existing owned-run exact-job monitor; no write is retried.

This tool does not transport plates or replace the composed transport scheduler.
Its initial plan confirms the plate is at site 4, matching loaded source/tip
inventory, arm at accepted empty HOME clearance or IDLE, and E-stop supervision.
No real protocol is created or executed merely by installing this feature.

The native catalog is independent of the commissioned recipe list. An empty
recipe list does not mean the instrument has no API or saved protocols.

`operator_ui/contracts/hamilton_openapi.json` is the pinned ML Prep API v1
snapshot already captured from this installation (318 operations, 279 paths).
SHA-256 of canonical JSON:
`3c7880a7b896d6032e37bd24298831bac71bdc51e73cc030a1059cca68e5c6ee`.
It contains API definitions, not credentials or experiment results. Updating
the snapshot changes its hash and invalidates pending request approvals.

## Model tools and UI

- `get_hamilton_api_catalog`: paginated search across every documented operation.
- `get_hamilton_api_operation`: exact method/path, parameter, body and response
  schemas, including referenced definitions and the access classification.
- `read_hamilton_api`: classified, schema-checked reads through the existing
  console-owned Hamilton adapter. No arbitrary hosts, headers or URL paths.
- `plan_hamilton_api_request`: one exact request in the existing pending-plan
  Yes/No flow. The researcher sees the method, path, body and completion limits.
- `get_hamilton_toolkit`: live saved protocols and local recipes, separately.
- `adopt_hamilton_protocol`: bind a saved native protocol to a fully specified,
  matching supported transfer specification without recreating it; then use
  the existing human-reviewed simulation and commissioning process.

The Hamilton panel has a read-only **Explore Hamilton API** section. Generic
API requests are reviewed in chat; browsing never starts an operation.

## Execution boundaries

The initial classification is 132 read operations, 141 human-confirmed
requests, two protocol-start/loading operations routed through the reviewed
protocol lifecycle, nine multipart imports requiring a file-upload adapter,
and 34 operator-only operations. Binary camera/report responses use existing
viewers rather than the text-read tool. This is full catalog coverage, **not
unrestricted execution of all 318 endpoints**.

Operator-only operations include authentication/credentials, account and
backup access, human signatures, and submission of calibration/verification
results. A model must not invent human attestations or calibration evidence.
An endpoint's method alone does not determine its effects: e.g. protocol
validation is a mutating GET, and disabling user management is also a GET.

Every executable request is bound to the schema hash, exact request,
Hamilton session, configuration, ten-minute expiry and single-use pending
plan. The shared runner and Hamilton ownership journal serialize work.
Timeouts are unknown outcomes; requests are never retried. A response to a
native asynchronous operation does not prove physical completion. Such a
request leaves a `finished_unverified` ownership hold for review and does not
authorize a robot transfer. Use existing monitored Hamilton workflows for
normal initialization, calibration and protocol execution.

Native physical protocol starts and load completion cannot bypass the
exact protocol, simulation, inventory, exact-job completion and approval
checks by going through the generic API. Use `plan_hamilton_experiment` to
combine simulation and execution without commissioning. Saved methods are not
automatically commissioned, and dry-air mocks are not liquid-qualified recipes.

## Adding liquid to occupied wells

`draft_protocol` now accepts either independent dilutions or `additions`.
An addition explicitly names source, destination, `volume_ul` and
`mix_after`. Initial liquid volumes/contents and source minimum remainders
are required. The compiler validates capacity, source balance, wells,
one fresh tip per transfer, exact 0.1 µL increments, and mixing volume.
It preserves existing native step compilation and simulation verification.

Current authoring scope remains aqueous transfers, Cellvis P24-1.5H-N at
site 4, 300 µL filtered tips (235903), 1–300 µL per transfer, and one reviewed
inventory cycle. No serial transfers, implicit volume defaults or automatic
physical retries are introduced. Adopting an existing protocol currently
requires matching this supported compiler shape; arbitrary native step
types remain inspectable/editable but are not automatically commissioned.

## Verification

Offline tests cover all catalog keys, mutating GET classification, typed
parameters/path injection, human approval, expiry/change binding, no resend,
asynchronous ACK ownership, occupied-well additions and the complete fake
create → simulate → commission lifecycle. No real hardware writes or recipe
commissioning are part of these tests.
