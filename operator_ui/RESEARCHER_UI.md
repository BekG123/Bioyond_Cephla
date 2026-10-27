# Cephla researcher workspace

Run the existing Flask app. `/` and `/researcher` open Prepare / Teach / Run;
`/developer` opens the existing console. This is a navigation split, not an
authentication boundary.

## Lacry question buttons

Lacry uses `ask_researcher` for questions, with Yes/No or named choices and a
written-answer field. Plain prose questions also receive fallback answer controls.
Each answer is bound to its current question ID; stale or duplicate clicks are
rejected. Typed Yes answers a pending question with its context. It only starts
hardware when answering an already displayed executable plan through the existing
confirmation path. Answering a setup question cannot approve a future plan.
Known workflows should be proposed with their requirements immediately, without
an extra readiness question before planning. Native Hamilton setup/unload dialogs
retain their dedicated instruction buttons and controller checks.

Validated with the rack/teaching-needle question regression, question HTTP routing,
existing plan-confirmation tests, and fixture-only Edge tests for Yes/No, choices,
written answers, refresh, duplicate clicks and mobile layout.

## Home → plate pickup → Hamilton

1. In Prepare, select **Connect robot**. This opens the configured shared TCP
   connection only; it never enables the arm or starts a controller program.
   Disconnect Bioyond Works first: only one application can own that connection.
2. In Teach, name the routine and select **Start teaching**. This opens a draft;
   it does not assume the current arm position is Home.
3. Use **Hand-guiding with DragGo** on this page: confirm the preparation
   checkbox and select **Start hand-guiding**. Wait for the active message,
   guide gently to Home, hold still, and select **Capture Home**.
4. For an existing Home-only draft, choose **Use plate workflow with this Home**.
   New drafts already use Home → Calibrate → Align → Descend → Grip → Hamilton.
5. Place both disks in view, release the arm, confirm empty jaws, clear hands
   and work area, and E-stop supervision; then select **Calibrate**. This explicit
   click exits DragGo, prepares Auto mode and the Lua program, and runs the
   existing `run_fast_disk` movement loop with **Wide fixed**. Starting Lua may
   close the empty jaws. A ready program is reused instead of restarted.
   The arm makes bounded corrections and captures fresh feedback itself.
   Two stationary images must meet XY <0.3 mm, Z <0.3 mm and yaw <0.2° and
   agree on the grasp pose. No time/travel/observation caps were added.
   Calibration does not require activating a workspace envelope; an enabled
   envelope is still respected, as are IK, joint and rotation-clearance checks.
   Progress shows the phase, initial/current residuals, completed corrections
   and confirmation count. **Stop calibration** cancels after the current
   movement finishes; the physical E-stop is separate. Hand-guiding controls
   cannot interrupt or compete with this automatic sequence.
   Each attempt writes its setup, measurements, image paths, requested/arrived
   movements and outcome to `operator_ui/reports/calibration/<session>.jsonl`.
   Session-specific image names prevent overwriting captures after a restart.
6. Select **Run Align** separately after calibration succeeds. Confirm empty
   jaws, clear hands/work area and E-stop supervision. Align exits DragGo,
   selects Auto, enables the controller and starts its Lua program (which may
   close the empty jaws). This uses the
   existing guarded geometric alignment; it does not use an untaught IC
   reference or descend. Align's existing envelope checks remain in place.
   Calibrate and Align are available in both Teach and Run. Calibration can be
   repeated after Home is captured, without Undo. Starting a repeat archives the
   previous waypoint list in the draft's `history` before invalidating the old
   step and its later records. A failed repeat retains that history but does not
   present the old completion as current. Align requires a fresh calibration
   target and a matching measured arm position; it can also be repeated from its
   verified endpoint. Keep the readiness checkbox explicit for either action.
7. Perform Descend manually using the existing controls, hold still, confirm
   that you performed it, and select **Record manual Descend**. Repeat for
   **Record manual Grip**. These buttons read poses, joints and native E1
   position twice; they send no motion/gripper commands. The grasp is recorded
   as operator-reported, not independently verified. DragGo's empty-gripper
   preparation does not authorize hand-guiding with a held plate.
8. Capture intermediate route points if needed, then **Capture Hamilton**.
   Review and save. Undo removes only a record; it does not reverse a physical
   action. Discard preserves previously saved routines.
9. Run lists saved routines and offers **Download measured positions**.
   Select **Check saved routine** to check pickup measurements and the Hamilton
   route using the same IK planner as Return Home. This is read-only: it does
   not move the arm or change limits. It lists missing measurements, incomplete
   descent, wrong gripper direction, workspace violations and IK failures.
   Physical Run / Pause / Stop remain unavailable until playback is implemented.
10. **Ask Haiku to plan pickup** sends a compact, measured excerpt of the linked
    continuous log, stage captures, and IK findings to Anthropic. It identifies
    Descend, Grip and the first lift as a proposal. Developer view displays the
    request, response and proposal; JSON evidence/results are saved under
    `reports/pickup_plans`. This does not approve a reference or execute movement.
    The current evidence bundle is linked to the October 16 Hamilton routine,
    revision 7; another routine needs its own linked recording. Connect Haiku
    in Developer view (also allowed during hand-guiding). Keys remain in memory
    and must be entered again after a console restart.

The browser practice mode has been replaced by real measured station capture.
Old localStorage practice data is ignored and never imported. Camera images are
not needed for station/manual-action capture; calibration uses the GigE camera.
Opening the page does not open a camera or start a robot action.

## Data and API

`researcher_teaching.py` stores drafts and reviewed routines atomically in
`operator_ui/demonstrations/teaching.json` (local data, ignored by Git).
Saved routines get unique IDs; new routines do not replace earlier ones.
Draft IDs and revisions reject stale requests and duplicate captures across tabs.

Exports use `cephla.station-demo.v1`: Home / optional intermediate points /
Hamilton, timestamped measured X/Y/Z/Rz and J1–J4, T0/U0 frame, millimetre/degree
units, controller endpoint, capture timing, and explicit limitations. Gripper
and image data are absent. This is a sparse waypoint dataset, **not sufficient
by itself to learn or validate the path between points**. Review is not motion
approval. `execution.ready` remains false until a real executor is integrated.

Capture samples fresh pose and joints twice, checks finite values, rejects
changes over 0.3 mm / 0.2 degrees or read windows over 3 seconds, and rechecks
controller status before committing. This checks snapshot consistency, not
collision clearance or future motion safety. It does not execute Lua jobs.
Failed reads/writes preserve the previous draft. The Flask dispatch lock rejects
capture while another command or sequence owns the arm. Capture never queues
behind a move to silently record a later position.

- `GET /researcher/api/status`: allowlisted status and summaries; no raw coordinates.
- `POST /researcher/api/connect`: shared configured connection, no enabling.
- `POST /researcher/api/hand-guiding/start`: explicit `ready: true`, verified
  disable → Manual → DragGo → enable. `/hand-guiding/end` disables and exits.
- `POST /researcher/api/teaching/start`: accepts a routine `name`.
- New UI drafts also send `workflow: "plate_pick_hamilton"`. Old two-station
  datasets remain readable. Explicit `/workflow/adopt` preserves an existing
  Home-only draft while selecting the new order.
- `POST /researcher/api/workflow/{Calibrate,Align}`: draft ID/revision plus
  `ready: true`; runs one background step. Calibrate prepares the controller
  and uses automatic `run_fast_disk(config='Wide')`. DragGo need not be active.
  Only successful completed stages
  are added to the demonstration, with measured final pose and result.
- `POST /researcher/api/workflow/stop`: cancels Calibrate or Align after the
  current movement finishes.
  This is separate from the unimplemented routine-playback Stop button.
- Manual Descend/Grip captures use `performed: true`; exported `command` is
  null and `grip_verified` false. They are observations, not executable commands.
- `POST /researcher/api/teaching/{capture,undo,discard,save}`: requires `draft_id`
  and `revision`. Capture also requires `station` (Home, Waypoint, Hamilton);
  save requires `reviewed: true`.
- `GET /researcher/api/routines/<id>/export`: measured data as JSON.

Device exceptions stay in developer logs. Playback POSTs return 501 even when
disabled buttons are bypassed. When integrating a model/executor, drive progress
from verified backend events and retain ownership, readiness, disconnect/fault
handling, and reviewed-data provenance. Flipping a capability flag is not enough.

## Shared Researcher / Developer audit log

The console automatically writes `operator_ui/logs/audit/<UTC-session>/events_*.jsonl`.
Each request and response shares a request ID and a view label. JSON bodies include
command targets (including gripper E1), returned results/errors, and timing.
Robot status records include measured poses, joints, external axes such as E1,
mode, enable state and faults. These reuse the existing status reads; logging
does not issue extra robot commands or create a second controller connection.
Background sequence start/progress/stop/result events persist even with no browser
polling. The sequence origin links back to the initiating request.

Developer view has **Download audit JSON** (`/audit/export`) and **Log status**
(`/audit/status`). Export is a snapshot of the current console session; previous
sessions remain on disk. Files rotate at 25 MiB and are never automatically deleted.
Set `CEPHLA_AUDIT_DIR` to use a different location. Logs are excluded from Git.

Passwords, tokens and authentication headers are omitted/redacted. Camera images,
static files and streams have response metadata only, not binary payloads.
This is application evidence, not synchronized servo telemetry or approved replay
data; it cannot reconstruct earlier events or movements made through other apps.
If storage fails, commands/Stop still work, `/audit/status` reports the failure,
and responses have `X-Cephla-Audit: error`. Normal responses say `recording`.

## Still pending

Physically validate the implemented DragGo activation/exit, add continuous
timestamped motion/gripper recording, and integrate/validate model playback.
DragGo now has direct Researcher controls; Bioyond Works stays disconnected.
Connect never enables DragGo. See [DRAGGO.md](DRAGGO.md) for firmware support,
exit behavior, verification, and recovery. Simulated drag recordings and
unrelated point lists must not be treated as measured demonstrations.

Physical Pause/Resume semantics need implementation and testing. Developer
**Stop Sequence** requests cancellation after the current step; it is not an
immediate halt. Program pause also cancels the high-level sequence, so it cannot
be presented as resumable demonstration replay. The physical E-stop is separate.

## Haiku Descend / Grip

Researcher **Run → Descend / Grip** requests one action in the background.
Developer **Haiku imitation — Descend / Grip** holds the API-key field, reference
review and complete model/tool transcript. Enter the key once in Developer view:
Windows encrypts it for the signed-in user with DPAPI and saves it outside the
repository at `%LOCALAPPDATA%/Cephla/haiku-key.dpapi`. Console restarts restore it
automatically. Entering a replacement key overwrites the saved credential.
Linux uses Python `keyring` with an unlocked Secret Service backend (install
`keyring` in the app environment). `ANTHROPIC_API_KEY` remains an alternative
when no saved key is available. Keys are never returned by the UI APIs.

1. Record measured Align, manual Descend and manual Grip endpoints using Teach.
   The October 16 collision export missed the descent and E1 movement, so it is
   included as diagnostic context only. The reported “0.2” is not an executable
   command. Do not use the collision pose as a taught endpoint.
2. In Developer view, load the current draft (or enter a saved routine ID), review
   the actual measurements, verify the clear vertical path and jaw clearance,
   then save the reviewed reference. Changed previews require a new review.
   `demonstrations/imitation_reference.json` stores the reviewed snapshot and
   source records; it is excluded from Git with the other demonstration data.
3. Add the Anthropic key. Calibration/alignment must leave the arm at the taught
   start, with the taught opening. Plate, T0/U0 frames and tool must be unchanged.
   No free-space route or alignment transformation is inferred from endpoints.
4. Press **Descend** in Researcher Run. Haiku receives the reference, current
   measurements, curated diagnostic export summaries and recent action outcomes.
   It selects `descend_to_reference`; the existing torque-guarded descent executes
   locally. The model cannot supply coordinates. Pose, Auto readiness, controller
   faults and the existing Descend/Grip workspace limits are checked again after
   the API reply. Calibration's envelope behavior is unchanged.
5. After successful descent, press **Grip** separately. `grip_to_reference` closes
   in increments no larger than 0.2 E1 units (the existing controller position
   units), speed 5, to the measured target. Torque, position and arm-pose checks
   run between steps. Contact/stall stops execution without automatic reopening.
   Reaching this position does not prove a secure grasp; no ascent follows.

Model requests, replies, tool results and errors appear only in Developer view
and persist in the shared audit JSONL. No raw camera frames or full audit traffic
are uploaded by this feature. This is **reference-conditioned imitation**, not
fine-tuning or trajectory learning. Client tool handling follows the
[Anthropic Messages tool-use API](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls).
The host accepts one allowlisted call, rejects additional tools/parameters, and
disables tools for the post-action reply. A model/API error never retries motion.

**Stop** prevents further increments after the current movement finishes; it also
prevents a pending model reply from starting motion. It is not a physical halt.
Pause is unavailable. Manual controls, new workflow operations, faults, server
restart or Stop invalidate permission to continue to Grip. The latest successful
Descend authorizes Grip for up to ten minutes. Full Hamilton playback remains
unimplemented. Live validation and a complete reviewed reference are still needed.

## Offline verification

```powershell
.venv-realsense/Scripts/python.exe -B operator_ui/tests/test_researcher.py
.venv-realsense/Scripts/python.exe -B operator_ui/tests/test_imitation_agent.py
.venv-realsense/Scripts/python.exe -B operator_ui/tests/test_audit_log.py
.venv-realsense/Scripts/python.exe -B operator_ui/tests/test_draggo.py
.venv-realsense/Scripts/python.exe -B operator_ui/tests/test_researcher_workflow.py
.venv-realsense/Scripts/python.exe -B operator_ui/tests/test_hand_calibration.py
.venv-realsense/Scripts/python.exe -B operator_ui/tests/check_researcher_browser.py
```

Browser QA uses a temporary Flask server, fake controller, temporary
teaching store, and headless Edge on Windows. It checks capture, undo, review,
save/export, DragGo start/exit, reload persistence, disconnect handling, and desktop/mobile layout.
It imports no physical robot/camera service and asserts no motion endpoints are
called. Screenshots go in `operator_ui/reports/researcher_ui/` (ignored by Git).
# Return Home

The Return Home card is available in every Researcher stage. It uses the Home
role in Developer saved points (currently the October 16 screenshot position).
Check the saved position and clear return route, confirm the empty gripper and
supervised E-stop, release the arm, then click **Return Home**. The same verified
preparation used by calibration ends DragGo and prepares Auto motion as needed.
Starting the controller program may close the empty jaws, as disclosed beside
the button. Unknown hand-guiding state or controller alerts block preparation.

The route raises to at least 300 mm (or higher when needed), rotates in checked
segments, moves above Home, and lowers to its saved Z. The complete route is
checked against workspace, kinematic and wrist limits before departure; these
checks do not detect physical obstacles. Stop finishes the current short segment.
Gripper commands and teaching edits are never part of this action. Calibration
and pickup execution context are invalidated when a Home return starts.

## Lacry complete experiment and chat answers (October 24)

The current Lacry chat shows **Yes** and **No** beneath an executable plan, using
the same controls styling. Yes confirms the exact displayed plan; No discards it.
Typing Yes still works. Buttons disappear while running, when cancelled, or when
the plan is blocked. Double-clicks do not dispatch two starts; stale plan IDs are
rejected by the host.

`plan_lab_roundtrip` plans repeated dispensing and imaging of the **same plate**:

1. Optional full calibration/pickup once, then Home.
2. Deliver to Hamilton and return Home.
3. Start the selected Hamilton protocol; wait at Home for its exact job.
4. Retrieve from Hamilton via Home; deliver to Squid; return Home.
5. Image with selected Squid settings; wait for that exact acquisition.
6. Return Squid stage to the accepted loading location, retrieve via Home,
   deliver back to Hamilton, and park Home.
7. Repeat steps 3–6 for the requested count.

One confirmation covers the complete displayed run. Host code owns ordering,
job identities, taught routes, plate location, and stop-on-failure behavior.
Records are in `reports/lab_roundtrip/<plan-id>/workflow.json`, including every
instrument ticket and phase. An incomplete record blocks a fresh run until
reviewed. Stop prevents subsequent robot steps; it is not an emergency stop and
does not currently abort Hamilton. Squid cancellation targets only an owned job.

### Hamilton connection template for developers

`hamilton_connection.json` remains disabled until a real local bridge is installed.
This is an integration contract, **not an assumed Hamilton vendor API**. Implement
these JSON endpoints using the actual instrument software, then enable the file:

* `GET /status`: `ok:true`, a nonempty `session_id`, `simulation:false`,
  `state` (`idle`, `running`, `completed`, or a fault), `ready_for_robot`,
  `protocols` (actual available protocol names), and current `job_id`.
* `POST /jobs`: accept `request_id`, `plate_id`, `protocol`, `session_id`;
  return those same identities, `ok:true`, and a unique `job_id`.
  Deduplicate request IDs. A lost acknowledgement is uncertain; Lacry never retries.
* `GET /jobs/<job_id>`: return all five matching identities, `ok:true`,
  `status` (`queued`, `running`, `completed`, `failed`, or `cancelled`),
  `success`, and `ready_for_robot`. Successful completion and robot access must
  come from actual instrument state, not elapsed time. A new bridge/instrument
  session must have a new session ID.

The default bridge address is `http://127.0.0.1:5055`. No bridge server or physical
Hamilton start/finish integration has been installed by this change.

Automatic Hamilton handoff also requires the existing supervised loaded drop-off
and retrieval checks to be accepted. Record them in
`reports/hamilton/automatic_handling_acceptance.json` with
`status:"operator_accepted"`, the exact `handling_evidence` from
`hamilton_handling.reference()[2]`, and `hamilton_dropoff` / `hamilton_retrieve`
objects containing `operator_accepted:true` and `report` paths relative to
`operator_ui` under `reports/`. Each report must record `ok:true`. Do not fabricate
acceptance: only this evidence replaces the existing manual inspection pauses;
motion, position, controller, and gripper checks remain active.

Validation: `tests/test_lab_roundtrip.py` exercises repeated cycles, the optional
calibration prefix, actual station planner/Lua with fake hardware, instrument
failures, uncertain acknowledgements, stop/reservation behavior and stale answers.
`tests/check_lacry_browser.py` tests Yes/No and layout with fixture-only APIs.
These checks do not constitute a live loaded Hamilton experiment. Current Squid
has a physical XYZ stage and simulated camera images.

### Retrieval after imaging started in Squid

If a plate is already at Squid, say **"When this scan finishes, bring the plate
Home."** `plan_squid_retrieval` also accepts an already completed tracked scan.
One Yes covers exact-job waiting, physical stage return to the saved loading
position, and the taught pickup/loaded return Home. It does not start another
scan, repeat drop-off, or perform native microscope homing. A successful scan
following a standalone drop-off offers this plan proactively; no motion starts
until confirmed. Existing full automatic workflows continue their authorized
retrieval without another confirmation.

`squid_retrieval.py` keeps the shared runner reserved across stage and robot jobs.
Failures, changed acquisition/session/reference, Stop, and an incorrect loading
position block progression. Logs live in `reports/squid_retrieval/<plan>/`.
`logs/squid/events.completion.json` preserves a verified observation across a
console-only reload, rechecked against the native current job/session/result.
Uncertain/disconnected observations invalidate it. This receipt is completion
evidence only, never movement permission. `tests/test_squid_retrieval.py` uses
fake hardware and includes the real station planner/Lua execution path.

October 24 regression: the first live continuation stopped before pickup because
the stage audit used `run_id` for Squid's scan, conflicting with the runner's
robot sequence ID. It now records `squid_run_id` and `squid_experiment_id`.
Stage/retrieval tests enable the event sink to reproduce this production path.
An embedded stage action no longer publishes overall workflow success; only the
completed robot pickup and verified Home return finish the combined retrieval.

October 24 imaging-selection fix: selecting a well or Current Position may move
the stage away from loading. Automatic experiments now capture settings there,
then include **Prepare Squid loading position** after the pickup has returned the
arm Home and before robot delivery. Multi-cycle workflows include the same step.
One Yes covers this stage return. Robot delivery still requires verified loading
feedback; a stage failure stops the workflow. Selection changes before Yes require
a fresh plan.

For the physical loading profile, imaging uses the captured native acquisition
YAML, preserving the selected XY/focus instead of capturing the drop-off position.
Live settings are checked at confirmation. Once confirmed, execution validates
the saved snapshot's integrity, session, loading reference and stage feedback;
it does not regenerate GUI sites. This is essential because Current Position at
loading can contain zero valid imaging fields. Later GUI edits do not change an
active confirmed run; stop and prepare a new plan to change it. Squid's shipped
code is unchanged. Offline tests exercise the selected-site/return/delivery order,
fixed imaging coordinates, changed settings, stage failure and no-motion planning.

The same experiment supports a plate **already held at Home**:
`plan_squid_experiment(pickup_from_calibration=false, retrieve=true)` skips all
calibration/pickup steps and keeps one confirmation through stage positioning,
delivery, imaging, exact-job completion, retrieval and Home. The host verifies
the taught Home pose, controller readiness and held-jaw setting before starting;
the researcher confirms plate security. It never prepares/restarts the controller
with a held plate. Generic station-action lists cannot sequence imaging; Lacry
must use this complete experiment tool instead of claiming separate Yes responses
are required. Tests cover actual taught Lua routes with fake hardware, no teaching
draft, changed jaws, failed acquisition, and typed confirmation.

The 02:27 loading-preparation failure was a redundant GUI recapture after the
physical stage return. Robot delivery and Lacry imaging never started. The
regression test now makes the GUI export fail with "Select the wells or imaging
locations" after loading and verifies the entire delivery/imaging/retrieval route
still executes the exact confirmed YAML, without any further GUI recapture.

New-plan recovery at loading: valid selections are persisted in
`squid_protocols.selection.json`. If Current Position has no imaging fields while
the stage is at its accepted loading target, the planner offers the latest saved
setup for explicit approval in the normal Yes/No plan. It names the saved site
and never calls it a live selection. Existing confirmed workflow logs supply the
initial setup when no cache exists. Session, configuration, loading reference and
snapshot hashes must match; network errors, changed sessions, or missing sites
away from loading do not trigger fallback. A recovered setup is settings only:
the new workflow requires a new Yes and never resumes an old failed motion.

October 24 scan-origin correction: the 03:00 run finished its images, but native
cleanup attempted to return to acquisition-start X0.050 while scanning limits
required X>=5 mm and timed out. The subsequent loading check measured X0.3183.
The complete workflow now includes **Move Squid into imaging area** after the arm
returns Home from delivery and before acquisition starts. It uses the confirmed
snapshot's first field after Squid's native scanning-position transition. No stage
limits are widened. `imaging_lifecycle.py` verifies native cleanup completion and
return feedback before the monitor reports success or allows loading/retrieval.
An old add-on is rejected before automatic physical workflows can run.

Deployment: tests use fake hardware. The host console can reload idle; the Squid
add-on requires a normal restart with operator-approved startup homing. The
prepared helper is `reports/restart_squid_lifecycle.ps1 -StageClearAndArmHome`;
it refuses if Squid remains open or the robot is not idle at Home. It does not
kill Squid or clear faults. The previous selected setup remains in
`reports/autonomous_squid/20261024T030016_59d772ee/confirmed_acquisition.yaml`.

October 24 retrieval planning correction: the 03:30 experiment completed imaging
and returned the stage to loading, but its plan had `retrieve_after_imaging=false`.
Lacry then incorrectly proposed calibration when told it forgot the plate.
A complete Squid experiment now defaults to retrieval to Home; leaving the plate
after imaging requires an explicit request. The host corrects an omitted retrieval
in complete-experiment proposals and routes forgotten-retrieval requests to the
tracked-job retrieval planner. That planner checks the job and route, requires a
fresh Yes, and cannot fall back to calibration on refusal. No already-confirmed
workflow is extended or silently resumed. Regression coverage includes both
reported chat messages, explicit no-retrieval requests, and refusal handling.

October 24 current-settings correction: a missing site at loading previously
substituted a whole saved acquisition, including an old one-time-point setting.
The add-on now exports live controls even with no fields. The host recovers only
compatible saved XY locations and combines them with live time, channel and Z
controls; the exact combined snapshot is rechecked at Yes and frozen afterward.
Changed tabs, objectives or XY layouts require a fresh site selection. An old
add-on cannot fall back to stale controls. This is a settings-transfer fix;
Lacry's prompt and memory were not changed. Squid needs a normal restart to load
the new read-only `get_current_acquisition_controls` command.

Imaging locations now persist across Squid restarts in
`squid_protocols.locations.jsonl`. Each capture retains its source session,
timestamp, controller/reference binding, layout, snapshot and checksums. New
proposals reuse the latest matching layout (Flexible and Wellplate are separate),
combine only its XY locations with live controls, and record that reuse. Process
ID changes alone do not invalidate locations. Controller, reference, layout,
checksum and current scan-limit checks still apply; already-confirmed plans remain
session-bound. Lacry captures valid locations before stage-only loading/homing
commands can clear them. Empty selections do not overwrite previous locations.
Records are reference/training data, not successful-trial labels or permission to
move. Workflow results remain in the experiment logs and reference the selection
record hash. No prompt or model-memory additions are used for this persistence.

Squid-only batches: ask “Run the Squid experiment 20 times using the current
settings.” `plan_squid_experiment(repetitions=20)` creates one plan and one Yes
authorizes the whole batch. Calibration/pickup happens once (or use the plate
already held at Home). Each cycle delivers the same plate, images it, verifies
stage cleanup/loading, retrieves it and returns Home before the next cycle.
Hamilton is not required. Repetitions count complete transfer cycles; Squid's Nt
still controls images/time points within each cycle. The UI shows completed
cycles, and each cycle saves its own acquisition snapshot, job ID and result.
Stop, uncertain completion or a fault ends the batch without silent retry.

After a controller reset, fault clearance and motion-program startup are separate.
Return Home can preview a route while the Lua program is stopped; its normal
confirmation includes empty-gripper startup. Queue/version checks run again before
travel. Missing/older published programs still block execution. Recover from fault
verifies actual servo feedback and reports a stopped program instead of implying
that travel is ready. Planning and page loading never restart the controller.
