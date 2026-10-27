# Hamilton integration in Lacry

Lacry connects directly to the physical Microlab Prep at `192.168.100.101/NimbusLite/api/v1`, serial `PRPGD2427`. Open the **Hamilton** instrument tile for status, a deck snapshot, calibration results, error history, calibration controls, and saved liquid-handling recipes. Opening the panel sends read requests only. Action buttons propose a plan in chat; they use the existing confirmation and runner ownership mechanism.

## Full calibration

**Full calibration** runs self-calibration, then channel height/squeeze calibration, sequentially under one plan confirmation. Lacry does not send a separate initialization beforehand; Hamilton owns the routine's internal preparation. Initialization remains a separately requested action. Native setup and completion dialogs appear in Lacry chat with Hamilton's Next/Finish button labels. Physical setup instructions require an operator response. The internal loading handshake continues under that confirmed setup after fresh rack and door checks. Follow the deck-clearing instruction first, then load the selected tip rack when Hamilton requests it. Rack placement is checked before accepting that loading dialog. Self-calibration requires a current success display and its completion dialog answered; channel calibration must produce a new passing result with valid Z offsets for both channels and no warnings. Idle or an old Pass cannot complete a new calibration. Failure, Stop or uncertain completion prevents the next stage.

The normal-polling comparison reported calibration-tool detection error 3844 and a front-channel Z travel-limit error before the host aborted. Reduced-polling self-calibration subsequently completed, including recognition and acknowledgement of the native Finish dialog. Logs retain the specific native faults rather than only the GenericBusy wrapper. These trials support a polling interaction without establishing the internal firmware cause.

**Touchscreen comparison:** In the Hamilton panel choose **Mirror touchscreen & record**, then start self-calibration or channel calibration on Hamilton itself. Native live instructions appear in Lacry chat; you can answer Next/Finish there, including choosing the loaded tip-rack site. Hamilton retains procedure ownership. The mirror never starts the next routine, acknowledges recovery dialogs, clears faults or aborts the touchscreen procedure. Use the touchscreen for unsupported selections and fault recovery. Connect the mirror before starting: the API does not provide the already-open dialog as a snapshot.

Each recording runs for up to one hour under `reports/hamilton_touchscreen/<timestamp>_<session>/recording.jsonl`. It captures native events, firmware/API trace windows, errors, run state and channel results. Trace window overflow is explicitly recorded; this is not continuous encoder telemetry or a guarantee that every internal firmware micro-move is exposed. Dialog answers are audited separately in `reports/hamilton_api/touchscreen_<token>.jsonl` and consumed once even if the HTTP response is lost. Disconnects, stale observations and changed dialogs block answers without retry.

Select the actual tip-rack site in the panel (default site 7). The configured rack is catalog 273, 300 µL framed conductive filtered. Load a full compatible rack, securely seated with its lid removed, and seat the teaching needle in its dedicated waste-block holder. The approved plan binds the site and rack definition; a fresh camera scan checks the rack before channel calibration. Tip-selection acknowledgements send the catalog database ID as a string (`"273"`) to `close-labware-view`; the start request uses numeric `273`. Live testing accepted this mapping. The part/reference number `235903` and the exported document GUID both returned HTTP 400; they are not substitutes for this field on the installed API. A closed-door prompt can be acknowledged within the approved sequence only when the original door/enclosure sensors confirm readiness. Unknown physical instructions stay visible for the operator. No calibration-result records are written by Lacry; results come from Hamilton.

Liquid-handling preparation and start require the latest channel calibration to pass. A combined experiment that explicitly includes full calibration can be planned before that pass exists, but liquid-handling execution still requires it. Calibration is a setup prerequisite, not something repeated on every cycle or every experiment. All calibration changes invalidate earlier camera-derived motion plans; those experimental scripts are not used by these buttons.

## Agent tools and experiment sequencing

**Park Hamilton** in the Hamilton instrument panel proposes `plan_hamilton(action="park")`.
After confirmation it sends native `PrepPark` and requires fresh `is-parked=true`
feedback. This is distinct from initialization and robot Home. The arm must
already be at Home; Hamilton must be Idle, empty of attached
tips/tools, with door/enclosure confirmed and no active service routine or pending
error. The operator confirms empty Hamilton channels and a clear parking path.
No automatic fault reset or motion retry occurs.
Parking does not require the host's initialization flag. Native `PrepPark`
decides whether it can execute from the current controller state. A rejection
is reported without automatic initialization, retries or synthesized coordinates;
support from every physical position has not been established by live testing.

The installed REST schema exposes parked status but no standalone park command.
This control uses the existing toolkit at `tmp/prep-jog-audit`, pinned to
`fc5ae129c39ef645a2a11234dce97f933a317a9c`, and native controller
`192.168.100.102:2000`. Transport open/close does not call high-level setup/stop,
initialization or coordinate moves. Stop requests native method abort through
the worker; uncertain completion retains ownership for review. This new control
has offline coverage; a live parking trial remains to be performed.

- `get_hamilton_status`: connection, initialization, current run, maintenance, errors, protocols and pending API prompts.
- `get_hamilton_toolkit(protocol_id=None)`: discover saved tests and commissioned recipe names, inspect a selected native protocol, and see remaining reviewed cycle inventory. This is read-only and pauses catalog inspection during calibration. Saved methods are not automatically approved recipes.
- `plan_hamilton(action, protocol, repetitions, tip_site)`: initialize when explicitly requested, self-calibrate, calibrate channel height/squeeze, run the full two-stage calibration, or execute a commissioned recipe repeatedly. Calibration setup is bound into the proposed plan; the host supplies the configured rack definition.
- `plan_lab_roundtrip(repetitions, hamilton_protocol, squid_protocol, pickup_from_calibration, hamilton_calibration)`: the existing same-plate Hamilton dispensing / Squid imaging / return loop, now backed by the Prep adapter. `hamilton_calibration=true` adds full two-stage Hamilton calibration once before the first delivery, using configured rack defaults. `pickup_from_calibration=true` separately adds the arm's full calibration and pickup before the loop.

One confirmation authorizes the entire displayed sequence, including all 25 cycles when requested. Successful waits and cycle boundaries do not request another Yes. A new physical instruction, fault, changed setup, or uncertain completion can interrupt the sequence. No model-accessible raw HTTP tool or separate MCP server is needed: Lacry's native tool registry calls the same host implementation as its GUI.

Researchers can ask “What tests are saved on Hamilton?”, “What does that test do?”, or “Run [approved recipe name] five times.” Lacry discovers the catalog, inspects the matching method when needed, and proposes the existing native API workflow. Ambiguous tests require clarification; unavailable recipes require commissioning. Hamilton's setup prompts continue in chat. This is access to supported API workflows, not a remote desktop or a promise that every touchscreen operation is implemented. No new hardware trial was performed when adding toolkit discovery.

## Current commissioning status

The original operator-confirmed touchscreen reference is channel result **1009** (Pass, both Z offsets valid, no warnings), using tip reference **235903 at site 7**. See `reports/hamilton_connection/touchscreen_calibration_reference_1009.json`. Lacry follows the same native self-calibration then channel-calibration stages without a separate initialization. On October 25 UTC, the default reduced-polling full-calibration run completed its self-calibration stage and advanced to channel selection. Channel selection exposed an incorrect ID mapping, corrected as described above; that run was stopped before pickup and the channel stage was restarted separately. This is not evidence of an uninterrupted full-chain success.

On October 24 (local time), touchscreen self-calibration and channel height/squeeze calibration completed successfully. Channel record 1008 is the first Pass in the returned channel history. A subsequent native two-channel diagnostic picked up tips from site 7, ejected them to waste, and finished parked/idle with no new errors. See `reports/hamilton_connection/Observations.md`. The single saved vendor protocol named `Protocol` is not evidence of a ready water-dispensing experiment.

`hamilton_prep.json` therefore contains no commissioned liquid-handling recipes. The existing loaded Hamilton handling acceptance requirement remains in `lab_roundtrip.py`. Connectors being available does not establish that tips, reservoir, plate, volumes, automatic door access, or the arm's loaded handoff are ready. A requested full experiment returns its complete preview and concrete setup blockers until those are verified.

Hamilton's protocol instructions require the door closed before execution. The installed `service-software-api/sensor-status` endpoint provides verified door/enclosure readings. The API exposes no motorized door open/close command. Autonomous round trips remain blocked on a supported door actuator or Hamilton-approved robot access arrangement. No enclosure settings or interlocks were changed. Robot access additionally requires a true `is-parked` response; idle is not a substitute.

## Recipe commissioning

Create and verify the liquid-handling method in Hamilton's software with the actual reservoir, tips, plate and volume settings. Record a supervised successful run and establish the handoff/door procedure before automatic lab round trips. Configure an entry under `recipes` with:

| Field | Meaning |
| --- | --- |
| `reviewed` | Set true only after the physical method and configuration are reviewed. |
| `protocol_id` | Actual numeric Hamilton protocol ID. |
| `protocol_hash` | `hamilton_prep.digest()` of the exact GET `protocols/{id}` response. |
| `inventory_id` | Unique identifier for a physically loaded inventory batch. Reuse the identifier while that same stock remains loaded. |
| `cycle_loads` | One entry per available cycle, each containing the reviewed `load_complete` inventory body and `load_instructions_hash` of that cycle's expected GET `protocol-run/load-instructions` response. |

Each cycle's inventory must account for remaining tips and liquids; do not repeat a full-tip-rack declaration after consuming tips. The adapter reserves each inventory entry durably before starting, including uncertain starts. A new process or experiment does not replenish inventory. Only physical replenishment and review justify a new inventory ID. Dynamic loading instructions that do not match a reviewed entry stop the run for inspection.

## Execution and recovery

### Native completion versus history publication (2026-10-26)

The installed API describes GET `calibration/channel-results` as previous results.
Two completed native runs left that history unchanged. Channel completion now
accepts a fresh passing report **or** the complete owned native lifecycle: confirmed
rack, completed loading, matching `Calibrate` activity start/end, acknowledged
cleanup, `CleanupFinished`, then a final `finished` event, initialized/Idle state,
no active protocol, no pending errors and no unanswered prompt. Error monitoring
remains active throughout. Idle or an old Pass alone cannot satisfy this check.

After a ten-second history-publication grace period, complete native evidence is
recorded as `channel_completion.source=native_lifecycle`. It means the procedure
completed; `numerical_result_verified=false` explicitly records that no new
numerical report was obtained. The host does not POST a fabricated calibration
result, change channel offsets, retry the procedure, or treat an actual failed
report as success. This supersedes the older new-history-only completion rule
described in the commissioning notes below.

### Calibration polling (2026-10-25)

All `HamiltonPrep.run_action()` calibration actions now use reduced polling by
default, including researcher UI plans, agent command batches and lab round trips.
The worker monitors connection/initialization, global run state, protocol state,
pending errors and error history. Native event/error subscriptions stay active.
Channel calibration additionally reads fresh channel results; accepting the native
tip-rack instruction still requires the existing deck scan. Door/enclosure checks
and native prompts remain required.

During the owned calibration, panel and agent status readers share the worker's
snapshot instead of issuing separate device requests. Parked-state, protocol
catalog, maintenance-list, trace and camera queries are paused. The UI labels the
camera as paused and removes its live indicator. Normal polling resumes on exit,
including failures. Parked status is not claimed from an old snapshot during a run.
The separate touchscreen observer pauses its HTTP samples while this worker owns
calibration; its event subscription remains passive.

Every Hamilton HTTP request through this adapter during calibration is recorded
under `reports/hamilton_api/polling_*/requests.jsonl`, with send/response/error
timing and suppression records. This does not capture unrelated clients. Explicit
developer comparisons can still select normal polling for one self-calibration;
ordinary researcher/agent operations need no polling parameter.

The initial reduced-polling self-calibration completed natively. A normal-polling
retry reproduced tool-not-detected and Z-limit faults. This supports a polling
interaction but does not isolate a specific query or eliminate controller-state
effects. See `reports/hamilton_connection/polling_comparison_result_20261025.json`.
The actual native `Calibration is complete.` Finish dialog is now recognized;
successful completion still requires acknowledgement, no fault, initialized state
and Idle. The earlier host failure record and its separate native-completion
reconciliation are retained.

The channel stage also emits a native `ShowDialog` from `Loads`. The adapter
starts `calibration/begin-load` for that owned dialog, waits for
`PrepareLoadingFinished`, then sends `calibration/end-load` after rechecking the
already confirmed rack and original door/enclosure sensors. This continues the
same loading instruction; it does not require another confirmation of unchanged
setup. Duplicate notifications never repeat writes. The ordinary
`protocol-run/load-instructions` endpoint does not serve this calibration dialog
(it returned HTTP 400 with protocol state Idle). The observed begin/end handshake
released the loading dialog and started the native Calibrate activity. Its first
live trial was recorded separately in `loading_handshake.jsonl` and
`loading_complete.jsonl` alongside the adapter request log.

The subsequent `Unloads` dialog requires `begin-cleanup`, then `end-cleanup`.
The observed sequence is `UnloadStarted`, `UnloadFinished`, operator acknowledgement
through `end-cleanup`, then `CleanupStarted` and `CleanupFinished`. The handler
now completes that handshake only on `CleanupFinished` while awaiting final
completion; the earlier `UnloadFinished` cannot acknowledge the later command.
Duplicate completion events send no writes. Fresh calibration-result verification
remains separate from the unload handshake.
Lacry checks parked/empty channels once after `UnloadStarted` and displays a
physical rack-removal instruction. Only the operator's response, with the door
closed, completes cleanup. This prevents a hidden unload prompt from appearing
to be frozen calibration.

Live channel trial `731faefc2a214375916c3a4825f47c00` performed squeeze,
tip-height and dispenser calibration, then finished and returned Idle after
operator-confirmed unloading. No new errors were reported, but no new channel
result was published: latest result remained the pre-existing Pass 3009.
This trial is **finished_unverified**, not Pass. The old tool-detection popup
remained on the touchscreen. The host monitor was retired by a guarded reload
after verifying native finished, Idle, parked and no attached tips; no redundant
abort was sent. The unresolved marker is retained and displayed after restart.
See `reports/hamilton_api/polling_20261025T080235Z_4e315de3/finished_unverified_review.json`.
The new handler stops waiting after a native finished/Idle state fails to produce
the required result, retains the review marker, and does not automatically retry.
The automated loading/unloading handlers have offline coverage; their first live
validation used recorded one-shot acknowledgements, not a fresh uninterrupted
run of the reloaded code. Result publication remains unresolved.

`hamilton_prep.py` subscribes to both event and error websockets before a start, records each outgoing write before sending it, and never retries a write. It checks error history as well as pending errors because the pending-error endpoint returned an empty list during the actual pickup fault. A protocol must match its unique `runDatalId`, physical serial number and successful `run-data/{id}` record. Idle alone is insufficient. No plate retrieval follows an aborted or uncertain result.

API dialogs are exposed in the panel with their actual identities. Calibration's successful final display can be acknowledged as part of the approved operation; other physical instructions require the operator to complete the displayed instruction. A lost event connection stops progression. Abort applies only to the operation owned by Lacry and is not declared complete until an aborted event and idle state are observed. An unbound or uncertain abort requires inspection at the instrument.

Journals and persistent inventory ledgers are in `reports/hamilton_api`. `active.json` survives a process interruption or uncertain outcome and blocks new operations. For recovery, inspect the instrument, its current run and the corresponding journal; resolve or abort the actual operation through the instrument controls, then archive the marker with the reviewed outcome. Deleting the marker does not stop hardware or restore consumed inventory. Never clear it merely to make a button work.

The older `hamilton_adapter.py` and simulated `hamilton_bridge.py` remain for legacy contract tests; the live backend uses `HamiltonPrep`. Calibration and protocols use REST; only explicit native parking uses the pinned toolkit connection described above.

## Verification

Offline tests cover the 25-cycle sequence with one calibration and one confirmation, exact-run success, aborted/stale results, empty pending-error responses during faults, connection loss, no write retries, persistent inventory, prompt identity, stop handling and concurrent operation rejection. The fixture-only Edge test covers the Hamilton panel at desktop/mobile widths and verifies that opening it sends no write request. No new motion is sent by these tests.

Vendor reference: [Hamilton protocol lifecycle](https://developer.hamiltoncompany.com/pages/prep_recipe_protocol_start). The installed API schema is retained at `reports/hamilton_connection/prep_openapi.json`; it is the source for request fields and run-result checks in this implementation.
# Route and handoff evidence recovery (2026-10-24)

The Home-Hamilton route is saved and matches the completed empty-gripper trial
`reports/hamilton/zero_roundtrip_20261020T113537Z.json`. Lack of unattended
commissioning must not be reported as a missing route.

The audit session `logs/audit/20261020T121524Z_d37ba039/events_0001.jsonl`
contains completed loaded drop-off (12:17–12:19 UTC) and retrieval (12:20–12:21
UTC), including both operator inspection approvals per run. These events and
their source line hashes are recovered in `reports/hamilton/loaded_handling_history.json`.
Two later failed attempts are retained too. Recovery records historical success;
it does not manufacture an unattended handling acceptance or door actuator.

Hamilton's panel now exposes **Leave plate at Hamilton** and **Retrieve plate
to Home**, using the existing supervised host routines and confirmation path.
Opening the panel or requesting a plan sends no movement command. Live model
context reports travel, supervised handling history and unattended commissioning
separately. Inspection checks remain in place.

The active arm route now uses the operator-accepted 26 October Hamilton endpoint:
X144.50/Y-350.68/Z61.22/Rz-3.00. Home-Hamilton travel uses the exact three-target
route tested in both directions at speed137. Hamilton-Squid travel chains through
true Home in either direction. `hamilton_endpoint.json` and
`hamilton_accepted_route.py` bind station recognition, return planning and local
handling to the same accepted evidence under
`reports/trajectory_smoothing/hamilton_reteach_20261026/`. Historical lower endpoints
remain in their original records. Pickup/release at the revised location retains
the supervised inspections and 5 mm slow lift; the travel trials do not commission
that local handoff or establish which payload was present.

`plan_tip_waste_experiment` preserves the distinct request to perform N two-tip
pickup/ejection pairs then one Squid imaging run, with requested calibrations
once. It is explicitly a blocked preview: the installed native diagnostic's
`TipPickupDiagnosticPutDto` has channel selection, labware, deck position and
eject-to-waste fields, but no pair count. It cannot guarantee exactly N pairs.
No liquid recipe is requested for this dry test, and no complete-loop or
multi-pair diagnostic substitution is allowed. Calibration tip use is additional.
