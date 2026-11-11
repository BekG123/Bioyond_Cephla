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

## Run the plate workflows from a terminal

Keep the Flask console running. From the repository folder:

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
