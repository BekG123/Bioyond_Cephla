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
