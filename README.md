# Bioyond_Cephla

<p>
  <img alt="Robot" src="https://img.shields.io/badge/robot-Bioyond%20S4-blue">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10+-informational">
  <img alt="Interface" src="https://img.shields.io/badge/interface-Flask-lightgrey">
  <img alt="Mode" src="https://img.shields.io/badge/mode-human--in--the--loop-orange">
</p>

**Bioyond_Cephla** is Cephla's research-and-production software platform for
automating laboratory experiments on the Bioyond LabGenius S4. It combines a
Flask operator console, MCP robot tools, calibrated vision, torque-guarded
motion, offline simulation, and versioned Bioyond controller packages.

The project is designed for real lab conditions: imperfect object placement,
changing calibration, hardware faults, and human review before motion.

## What this is

Legacy standalone ArUco utilities and marker images are in [`Misc/aruco`](Misc/README.md).
Shared vision and calibration dependencies remain in their existing packages.

A human-in-the-loop robotics repository for a real lab cell:

- `operator_ui/` — Flask researcher/developer console and guarded sequences.
- `bioyond-s4-mcp/` — MCP server exposing robot and camera tools to agents.
- `grab_skill/` and `Pick and Hold/` — vision, calibration, alignment,
  descent, and grip pipelines.
- `controller/` — versioned Bioyond controller packages and manifests.
- `docs/` — design, handover, report, and calibration evidence.

## Intelligence Over Precision paper

This repository is the implementation and evidence base for our paper,
**Intelligence Over Precision**.

The central idea is that useful laboratory automation should not depend on
perfect placement or perfect calibration. Instead, the system measures the
scene, constrains motion, checks torque and arrival, records evidence, and asks
a human to review decisions that still need judgment.

Key evidence and design material:

- [System design](docs/DESIGN.md)
- [Robot, calibration, and safety handover](docs/HANDOVER_MCP_SKILLS.md)
- [Operator UI handover](docs/HANDOVER_OPERATOR_UI.md)
- [Progress report](docs/reports/Bioyond_S4_Progress_Report.pdf)
- Experiment observations under `Pick and Hold/` and `operator_ui/reports/`

## Documentation

Start here depending on your role:

- **Using or extending the repo:** this README and [docs/DESIGN.md](docs/DESIGN.md)
- **Driving the physical robot:** [CLAUDE.md](CLAUDE.md), then
  [docs/HANDOVER_MCP_SKILLS.md](docs/HANDOVER_MCP_SKILLS.md)
- **Working on the Flask console:** [docs/HANDOVER_OPERATOR_UI.md](docs/HANDOVER_OPERATOR_UI.md)
  and [operator_ui/README.md](operator_ui/README.md)
- **Publishing controller programs:** [controller/README.md](controller/README.md)
- **Using MCP tools:** [bioyond-s4-mcp/README.md](bioyond-s4-mcp/README.md)

## How to setup

There are two easy ways to set up the project.

### 1. Classic CLI setup

#### Windows PowerShell

Install Git and 64-bit Python 3.10, then:

```powershell
git clone https://github.com/BekG123/Bioyond_Cephla.git
cd Bioyond_Cephla
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install flask numpy opencv-python PyYAML
.\.venv\Scripts\python.exe operator_ui/app.py
```

Open [http://127.0.0.1:5002](http://127.0.0.1:5002).

#### Linux / Ubuntu 22.04 desktop

```bash
sudo apt update
sudo apt install git python3.10-venv libgl1 libglib2.0-0 libglfw3
git clone https://github.com/BekG123/Bioyond_Cephla.git
cd Bioyond_Cephla
python3.10 -m venv .venv
.venv/bin/python -m pip install flask numpy opencv-python PyYAML
.venv/bin/python operator_ui/app.py
```

Open [http://127.0.0.1:5002](http://127.0.0.1:5002).

### 2. Agent setup prompt

For a token-efficient agent setup, open the repository root and paste:

```text
Set up this repo for local/offline use. Read README.md, CLAUDE.md, and docs/DESIGN.md section 12 only. From the repo root, create .venv with Python 3.10 and install flask numpy opencv-python PyYAML. Do not connect to the robot, cameras, Bioyond Works, or run motion/enabling commands. Run tests/test_offline.py from operator_ui/ with the venv Python. Report commands run, failures, and the exact command to launch http://127.0.0.1:5002. Ask before any hardware access.
```

## Optional components

- **Camera console:** install `anthropic` plus
  `bioyond-s4-mcp/requirements.txt`, then run `python camera_gui/app.py` for
  `http://127.0.0.1:5001`.
- **MCP server:** install `bioyond-s4-mcp/requirements.txt`; `.mcp.json` already
  registers `bioyond-s4-mcp/server.py`.
- **MuJoCo:** install `mujoco_sim/requirements.txt` in `mujoco_sim/.venv`, then
  run `mujoco_sim/open_project.py`.
- **D405 depth:** follow `operator_ui/REALSENSE.md`, then install
  `operator_ui/requirements-realsense.txt` into `.venv-realsense`.
- **GigE camera:** install the HIKROBOT MVS SDK and Python bindings; close other
  camera viewers first.
- **Controller packages:** publish the required `.bin` from `controller/` via
  Bioyond Works. Do not publish during basic software setup.

## Repository layout

| Path | Purpose |
| --- | --- |
| `operator_ui/` | Main Flask app, robot service, sequences, tests, and logs. |
| `controller/` | Bioyond `.bin` packages and build manifests. |
| `docs/` | Design, handover notes, reports, images, and calibration notes. |
| `bioyond-s4-mcp/` | MCP server, hardened TCP client, and camera helpers. |
| `camera_gui/` | Standalone three-camera viewer and annotation console. |
| `grab_skill/` | ArUco/world solving, calibration data, standalone grabber. |
| `Pick and Hold/` | Calibration, alignment, descent, grip, and observations. |
| `mujoco_sim/` | Offline MuJoCo scene and demos. |
| `arducam/` | Arducam model and detection experiments. |
| `Bioyond_S4_Agent_Context_Pack/` | Vendor manuals, protocol, and Lua sources. |
| `Vision_context/` | Vendor vision SDK and reference material. |
| `CLAUDE.md` | Operational contract for agent-driven robot work. |
| `.mcp.json` | MCP registration and environment defaults. |

## Development

Run the main offline suite before changing robot-facing behavior:

```bash
cd operator_ui
../.venv/bin/python tests/test_offline.py      # Linux
..\.venv\Scripts\python.exe tests\test_offline.py  # Windows
```

Controller-package builds are handled by the scripts in `operator_ui/` such as
`build_trajectory_program.py`, `build_descent_program.py`, and
`build_grip_program.py`. Outputs and manifests belong under `controller/`.

## Lacry chat through Codex and MCP

Lacry keeps its existing chat box, questions, plan cards and Yes/Stop controls.
The default backend is now `codex_mcp`: a local Codex app-server session uses
ChatGPT sign-in and calls Lacry's existing workflow tools through MCP. It does
not call Anthropic, and it refuses API-key authentication rather than falling
back to separately billed model APIs. ChatGPT/Codex plan usage limits still apply.

The MCP server is `operator_ui/lacry_mcp_server.py`. It forwards named tools to
the authenticated loopback backend; the existing Lacry service remains the sole
hardware owner. MCP exposes planning, status, memory, camera and Stop tools.
Human plan confirmation remains in Lacry, outside the model's tool catalog.
The Codex thread ID is retained locally so subsequent messages share context;
it is separate from any existing Codex desktop conversation.

Initial setup, from this repository:

```powershell
py -m venv .venv-lacry-mcp
.\.venv-lacry-mcp\Scripts\python.exe -m pip install -r operator_ui\requirements-lacry-mcp.txt
.\.venv-realsense\Scripts\python.exe -m pip install -r operator_ui\requirements-documents.txt
codex login
codex mcp add lacry -- "$PWD\.venv-lacry-mcp\Scripts\python.exe" -B "$PWD\operator_ui\lacry_mcp_server.py"
```

Start or restart the idle, disconnected Lacry service, then refresh its page:

```powershell
.\.venv-realsense\Scripts\python.exe -B -u operator_ui\app.py
```

The chat label reads **Agentic Lab Assistant**; the Developer model-status endpoint
reports `provider: codex_mcp` and `authentication: chatgpt`. A new Codex client session may
be needed to load the registered MCP server. The Lacry UI starts its own session
on the first message. No robot connection, enable, fault reset or motion is
performed by installing MCP or starting the chat session. Existing controller
and instrument connections/readiness are still required for workflow execution.

State and logs are in `operator_ui/logs/lacry_codex/`; the local MCP credential
is generated there and excluded from Git. Temporary MCP connection failures and
pre-dispatch lock contention recover automatically with the same request ID
(up to six attempts within 100 seconds). Saved replies survive a backend restart
in `requests.sqlite3`; recovering a reply does not invoke the tool again. Stop
cancels queued mutation retries. Missing sign-in and interrupted model turns
still return an error; model turns are not automatically resubmitted.
Legacy Anthropic chat/analysis requires the explicit environment override
`LACRY_LLM_PROVIDER=anthropic`; it is disabled by default, including the old
Developer image-analysis API path. Use Lacry's MCP camera tool for image review.

Offline regression tests: `operator_ui/tests/test_lacry_mcp.py`.
`operator_ui/tests/check_lacry_mcp_transport.py` verifies real stdio MCP against
an isolated read-only fixture; `--codex` additionally exercises a real
ChatGPT-authenticated Codex turn, consuming normal plan usage but operating no
hardware. Run the former with `.venv-lacry-mcp` Python and the latter with
`.venv-realsense` Python.

### Automatic recovery: first implementation

`lacry_recovery_status` exposes recovery policy and recent request receipts. Pass
the exact `request_id` from an interrupted call to recover its saved response,
then read `lacry_state` for the current plan/run. Receipts describe tool calls,
not physical completion. An executing request from a previous backend process
is reported as `outcome_unknown` and is never dispatched again. Keep the journal;
deleting it removes duplicate-request protection. It contains local tool results,
including any returned camera data, and stays in the ignored log directory.

The initial blocker audit separates these cases:

| Blocker | Current recovery |
| --- | --- |
| Temporary MCP disconnect or lost reply | Reconnect with the same request ID; recover a saved reply without repeating the tool. |
| Tool/control lock busy before dispatch | Wait and retry within a fixed budget; Stop cancels queued mutations. |
| Backend restarted after a tool completed | Return its durable receipt; inspect current state before continuing. |
| Backend restarted while a tool was executing | Preserve uncertainty; inspect the receipt and live state, never replay the operation. |
| Composed transfer failed before any hardware dispatch | Release its own transfer lock after saving the refusal; a fresh checked plan is possible. |
| Small HOME offset, holder deflection, first-side barcode no-read | Existing accepted tolerances, bounded holder correction and second-side scan remain in the validated executors. |
| Expired plan, changed geometry, unsupported plate/route | Replanning/qualification is still required; recovery does not manufacture acceptance. |
| Robot fault, jam, unknown payload or uncertain physical step | Physical recovery remains gated by the existing evidence and supervision requirements. No automatic reset or loaded restart. |

This adds unattended software recovery. It does not yet provide unattended
physical fault recovery or automatic restart of interrupted experiments. Those
need verified payload/occupancy observations and commissioned recovery routes.
No hardware is moved by the recovery-status tool or by installation.

Offline recovery tests are in `operator_ui/tests/test_lacry_recovery.py`; transport
fault injection is in `operator_ui/tests/test_lacry_mcp_reconnect.py` (use the MCP
venv, which has the MCP SDK). The existing workflow tests verify that an uncertain
physical step retains its hold and prevents remaining steps from running.

## Run the plate workflows from a terminal

Run these commands from the repository folder.

### Cellvis slot 1 to Squid or Hamilton

`operator_ui/run_plate_transfer.py` chains the existing workflows:
**slot 1 → HOME → barcode scanner → HOME → selected station**.
It supports the lid-off **Cellvis P24-1.5H-N** and the recorded Cellvis slot-1
retrieval acceptance. A successful fresh barcode scan saved to the registry is
required before station handling. No barcode ID is required beforehand.
The default runner is standalone: no Flask server or operator console is needed.
It opens its own robot connection and disconnects when finished. Disconnect any
other robot client first; the controller permits one connection owner.

```powershell
# Offline preview: no console or hardware connection.
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_plate_transfer.py --source-slot 1 --destination squid
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_plate_transfer.py --source-slot 1 --destination hamilton --roundtrip

# Leave the plate at the station; return the empty arm HOME.
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_plate_transfer.py --destination squid --drop-off --execute
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_plate_transfer.py --destination hamilton --drop-off --execute

# Deliver/release, then retrieve/reseat the plate in HOME.
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_plate_transfer.py --destination squid --roundtrip --execute
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_plate_transfer.py --destination hamilton --roundtrip --execute
```

Slot 1 and drop-off are the defaults. `--to` aliases `--destination`.
Add `--expected-plate-id "EXACT-BARCODE"` only when already known; the existing
registry/profile/location checks apply, and scanning still occurs. Omit it for
an unregistered plate. A mismatch or scanner error stops before station handling.
Five ordinary no-reads on each side return the plate HOME and block delivery.

`--execute` confirms the setup printed by `--help`: empty arm at accepted HOME
clearance, healthy running Auto/Lua, plate in slot 1, HOME and destination empty,
unchanged fixtures, clear routes/holder rotation, and E-stop supervision.
Slot-1 retrieval accepts an empty-arm HOME start within 0.5 mm horizontal
distance, 0.05 mm height and 0.2 degrees wrist rotation of its saved reference.
It validates the approach from the measured pose and joints; contact positions,
later arrivals and movement since preview retain their existing tight checks.
Hamilton requires parked heads and open access; Squid requires its verified
loading position. The runner connects automatically, but does not start/reset
the controller or calibrate. Roundtrip retrieves immediately; it does not wait for or start
imaging or pipetting. It returns the plate to HOME, not to the hotel slot.

Station readiness uses the instrument's own connection: Squid's control server
or Hamilton's API must be reachable. Neither check requires the Flask console.
Ctrl+C cancels the foreground workflow and requests Stop; software Stop is not an E-stop.
Timeouts, uncertain results and failed phases are never automatically retried.
Records are saved in `runs/composed_transfers/<run-id>.json`; unresolved runs
retain their existing lock for physical-state review.

Lacry's `get_workflow_catalog` discovers every installed agent/facade tool directly
from its registered schema. Its compact index gives descriptions and input names;
`get_workflow_catalog(workflow="plan_hamilton_experiment")` retrieves the full
schema for any indexed tool. Adding a tool does not require updating another
discovery whitelist. Discovery does not imply live readiness or composability.
The catalog also exposes the declarative contracts in
`operator_ui/workflow_capabilities.json`: plate profile, executor, preconditions
and postconditions. `plan_workflow` composes these by state rather than requiring
an entry for each complete operation order. Hotel retrieval, Cellvis registration,
Squid/Hamilton delivery, retrieval and instrument jobs are registered. Retrieval already includes release in HOME, so an
explicit `return_HOME` goal adds no duplicate movement. A subsequent retrieval
uses the latest fresh completed delivery/custody receipt and checks current
pose, jaws, holder, plate identity, route hashes and station readiness. It uses
the existing Cellvis executor under the shared runner and one confirmation.
Instrument jobs preserve station custody; `return_HOME` requests retrieval.
Transport prerequisites are expanded in the plan, including either instrument
order. `plan_workflow(..., draft_id="...")` binds the existing Hamilton create,
simulate, and conditional live-execution engine after delivery under the same
approval; `recipe` selects a commissioned method instead. Complete inventory,
settings, exact-job checks and the unchanged protocol remain bound. No-mix
additions do not require invented mixing parameters. Native writes and motion
occur only after human confirmation, with no retry on uncertainty.
Other specialized workflows remain discoverable through their own planners;
joining them requires an explicit compatible executor contract. Archived
successful trials are evidence, not automatically imported executable tools.

The optional `--via-console` flag selects the older Flask transport instead.
Only that mode requires a running, updated console with its robot connected.

The terminal wrapper and all four destination/finish combinations are tested
offline. This change does not claim a new physical handling trial.

### Existing calibration and station round trips

These older runners use the Flask console; keep it running for the commands below.

```powershell
# Preview: no hardware commands.
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_plate_workflow.py --full-calibration --home-to-hamilton-roundtrip --home-to-squid-roundtrip

# Run the same sequence after checking the setup.
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_plate_workflow.py --full-calibration --home-to-hamilton-roundtrip --home-to-squid-roundtrip --execute
```

Use any one flag, or combine them. Order is always calibration, Hamilton,
then Squid. Both round trips include delivery, release, empty return to HOME,
retrieval and release back in HOME. They do not run pipetting or imaging.
Add `--cycles 5` to repeat the selected station round trips five times.
Calibration runs **once before the loop**, even with `--full-calibration`.
The default is one cycle. Each completed cycle is recorded; a failed or
uncertain step stops the batch without a retry or starting the next cycle.
Repeating both stations requires fresh calibration evidence (`--full-calibration`
or `--calibration-record`); after Squid, the existing checked exchange rotates
the released holder back for Hamilton using that same session reference.
The original 30-minute calibration-evidence lifetime remains enforced.
Full calibration visits IDLE first, then finishes with the plate released in
HOME and the empty arm raised 30 mm. Station transfers have no IDLE detour.

The controller must already be running and fault-free. Before executing,
the plate must be supported in HOME, the selected destination holders empty,
Hamilton access open when used, routes clear, and the E-stop supervised.
Calibration requires released jaws at HOME; at IDLE, it can open confirmed
empty jaws. The runner never resets faults or starts a stopped Lua program.

For the accepted **Cellvis P24-1.5H-N, lid off**, use its separate runner:

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_cellvis24_workflow.py --full-calibration --home-to-hamilton-roundtrip --home-to-squid-roundtrip --cycles 5 --execute
```

Omit `--execute` to preview. This calibrates once, then repeats both station
round trips five times. It uses fresh Cellvis rim/grid measurements, its accepted
grip height and station routes; a changed plate placement stops before descent.
Start at IDLE or accepted Cellvis HOME clearance with empty jaws and the plate
supported in HOME. The combined runner is offline-tested; a new live run remains
to be verified. See [the Cellvis skill](<Codex SKILLS/cellvis24-calibration-station-workflow-v1/SKILL.md>).

For a Cellvis plate already held at the scanner after the accepted scanner
workflow, preview the return to HOME and rack-clearing Hamilton round trip:

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_cellvis24_scanner_hamilton.py
```

Add `--execute` for the supervised run. It returns to HOME, pauses for seating
inspection, releases and rotates the holder, then takes the plate to Hamilton
and back to HOME without releasing at Hamilton. Travel uses one Lua queue per
direction at137; final seating/departure remains5. It does not visit IDLE or
run calibration, pipetting or imaging. The CLI is offline-tested; combined
physical validation is still pending. Use `--from-home --source <receipt.json>`
to start from a fresh verified HOME release/reseating receipt. An interrupted
run requires inspecting and recording recovery, not rerunning its old receipt.

The optional shorter Hamilton candidate is previewed with:

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_cellvis24_scanner_hamilton.py --from-home --direct-hamilton
```

It turns the wrist above HOME at X306.20/Y-62.88/Z110.65, then crosses directly
to site4 at Z77, preserving the Z53.72 endpoint. This changes the rack sweep;
review the full loaded clearance before a physical trial. Publish
`controller/main_hostpoint_mixed_wrist137_queue_220111.bin` for the optional
fixed-position wrist `MoveJ` commands within the same queue as linear travel.
Old routes retain their previous behavior. After publishing and clearance review,
add `--source <fresh-HOME-receipt.json> --execute --direct-clearance-confirmed`.
The shorter route is not yet physically tested or selected as the default.

When skipping calibration, the runner selects the newest completed HOME
receipt, valid for 30 minutes. The backend checks the current pose, holder
angle, grip and unchanged route against it. Use `--calibration-record PATH`
or `--source PATH` to select evidence explicitly. A rejected receipt stops
the run; it does not fall back or retry. Hamilton can start from fresh
calibration or a completed Hamilton HOME release; Squid also accepts a
completed Squid HOME release. A different starting state needs preparation.

Grip approach uses speed 10 to 1 mm before the accepted target, then speed 5
for the final millimeter (long side: 4.9 to 3.9 mm; short side: 26 to 25 mm).
Opening speeds and travel paths are unchanged. Logs are saved under
`operator_ui/reports/plate_session/continuous_grip_handling_*/run.json`.

HOME release adjustment (November 11): both Hamilton and Squid returns descend
directly to a seating endpoint 1 mm below the pickup height in one continuous
6 mm move at speed 5. There is no stop at the old seating height and no separate
1 mm command. After arrival verification, open to 28 mm and return to the
existing empty-arm clearance height. Pickup heights and the full-calibration
finish are unchanged. The operator accepted the continuous-seating workflow
after one completed combined Hamilton/Squid cycle on November 11. The preceding
five-cycle record includes the slight HOME drop that prompted this adjustment.

## Safety

This repository controls physical machinery. For any live motion:

- Keep a person at the E-stop.
- Require explicit operator confirmation before enabling, clearing errors, or
  moving.
- Keep Cartesian moves inside the commissioned workspace envelope.
- Treat timeout or connection loss as unknown physical state; re-query status
  and pose instead of resending.
- Stop and restart the controller program after publishing; do not resume old
  paused code.
- Remember that only one application can own the robot TCP connection or GigE
  camera at a time.


## HOME / IDLE location contract (2026-11-10)

IDLE is the former true Home at X289.97/Y62.63/Z248.02/Rz-3.88. HOME now
means the calibration holder, with separate seating, clearance and grip poses.
Historical coordinates, controller route keys and trial hashes stay unchanged:
in the legacy procedures below, Home means IDLE unless explicitly marked HOME
holder. The old Home-area remains a distinct historical waypoint.

For a new experiment, use `operator_ui/plate_session.py` and
`Pick and Hold/plate_session_workflow.json`: full calibration once per valid
session -> grip -> lift 5 mm at speed 5 -> lower the same 5 mm at speed 5
into the unchanged HOME holder -> open E1 to 28 mm while seated -> raise the
EMPTY arm 30 mm at speed 137. Full calibration ends here, with no final IDLE
travel. Separately verify the full sweep -> orient -> verify three fresh E2
readings -> re-grip -> proof lift -> accepted destination route. The revised
calibration finish is implemented and offline-tested; its exact physical
trial is pending. Earlier 5 mm empty-clearance evidence is not that trial. Never rotate a held plate. The new near-holder
rotation is prepared, NOT yet physically commissioned; the old rotation trial
was with the arm away at IDLE. Do not substitute it as clearance evidence.

Hamilton first (selected for the next supervised trial): absolute E2 target
90.71661229181757 degrees (90.717 displayed), tolerance 0.1 degree, using the
accepted short-side E1=25 mm profile. Positive E2 from the original orientation
was observed counterclockwise from above. Do not command current E2 plus 90.
Squid first: no rotation, verify E2 around 1.77 degrees using the existing rule
`round(E2, 3) >= 1.769 and E2 <= 1.82`, and use the accepted 48-well long-side
grip. A wrong original angle requires review, not a blind no-op or re-grip.

Lacry chat uses `move_idle` for old parking and `move_home` for the new holder
preparation preview. `/researcher/api/lacry/button/move_idle` selects old
parking. Legacy developer planner `propose(['move_home'])`, controller job names
and archived scripts still refer to IDLE; do not change their recorded poses.
The new preview API is POST `/researcher/api/lacry/plate-session/plan` with
`{"first_destination":"Hamilton"}` or `"Squid"`. It is not executable until
the new released-plate placement/clearance/re-grip connection is reviewed.
Do not claim it ran or bypass the preview with old compound station travel.

Session reuse is tied to completed full calibration plus setup fingerprints.
Restart, fault/disconnection, hand-guiding, changed references or uncertain
motion invalidate reuse; physical fixture changes must also be reported.
Keep the E-stop supervised, envelope/IK and payload checks, and stop on faults,
uncertain grip/position or timeout. No automatic retries or controller restart
with a held plate. No existing trajectory was requalified by this name change.

## Supervised single-plate experiments (integration preview)

Hotel transfers planned through Lacry include released-holder preparation when
needed: at stationary HOME clearance with operator-confirmed empty jaws and an
empty HOME fixture, open the jaws to 28 mm and restore the holder to 1.77 degrees
before retrieval. This is displayed in the same human-confirmed transfer plan;
planning sends no commands. It reuses the bounded holder command sequence and
verifies the existing 1.740–1.820 degree arrival band. A failed opening, timeout,
changed pose or failed angle check stops the chain without retry. Preparation
receipts are stored under `operator_ui/reports/plate_session/hotel_holder_preparation`.
No calibration, arm route, barcode requirement or instrument workflow is changed.
After slot-1 retrieval reseats and releases the plate, scanner-bound transfers
recheck the holder at HOME clearance. They allow one correction of residual
seating deflection within the existing 0.5-degree contact band to 1.77 degrees,
with empty jaws verified at 28 mm, then require the original 1.740–1.820 degree
arrival band. The correction and original readings are recorded before the
retrieval receipt is finalized. The scanner's strict receipt check remains;
old failed receipts are neither rewritten nor automatically resumed.
The composed scanner executor also includes a source-bound re-centering step
immediately before each barcode presentation. Its read-only plan permits drift
within the same 0.5-degree contact band, while execution requires open jaws and
stationary HOME clearance, commands 1.77 degrees once, and verifies the strict
arrival band before approach. This covers drift occurring after the hotel
receipt was finalized. Standalone trial previews retain their strict gate
unless this preparation is explicitly included; failed commands are not retried.

The supervised scheduler composes accepted Cellvis handling with commissioned Hamilton recipes and exact Squid job waits. See [SCHEDULER.md](docs/SCHEDULER.md) for scope, approval/presence controls, offline checks and execution requirements. Lacry also supports [independent dilution authoring](docs/PROTOCOL_AUTHORING.md): local draft, human-approved native creation and simulation, then human-reviewed recipe commissioning. The dilution review table is in Researcher view. This version is supervised, sequential and has no automatic hardware retries; a new recipe requires its own simulation and human review before physical execution.
