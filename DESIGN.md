# Bioyond S4 Cell — Design Document

Audience: developers (human or agent) joining or continuing this project.
This document explains **how the system is put together and why**; it does
not duplicate the day-to-day operating instructions. For those, see:

- [`README.md`](README.md) — install/run instructions, progress tracker.
- [`CLAUDE.md`](CLAUDE.md) — the operational contract for an agent driving
  the robot (tool list, session bring-up, safety rules).
- [`HANDOVER_MCP_SKILLS.md`](HANDOVER_MCP_SKILLS.md) /
  [`HANDOVER_OPERATOR_UI.md`](HANDOVER_OPERATOR_UI.md) — exhaustive,
  measured, dated engineering notes (kinematics constants, hard-won
  lessons, physical state at last handover). Read those before touching
  the live robot; this document is the map, they are the territory.

---

## 1. What this project is

Software to drive a **Bioyond LabGenius S4** — a 4-axis SCARA-type lab
automation arm (joints J1 vertical ram, J2/J3 planar links, J4 wrist yaw;
external axes E1 gripper, E2 rotator, E2 effectively unused) — through
three parallel front ends that all sit on the same hardened control layer:

1. **An MCP server** (`bioyond-s4-mcp/`) so an LLM agent can query and move
   the robot via tool calls (natural-language-driven automation).
2. **A Flask operator console** (`operator_ui/`) — human-in-the-loop: an
   operator watches the eye-in-hand camera and presses buttons; the
   software executes one guarded step at a time.
3. **A standalone CLI grabber** (`grab_skill/grab_aruco.py`) — the full
   autonomous pick pipeline with no browser/MCP in the loop, for
   scripted/unattended runs.

The **current active focus** is a fourth, simpler workflow built on the
same control layer: letting a researcher physically guide the arm through
a task and have the system record and replay it. See §2.

Secondary, more experimental work streams build on top of or alongside
this core: offline simulation (MuJoCo), depth sensing (RealSense D405,
Depth Anything V2), and general-purpose vision (Arducam + SAM/DINO/YOLO).
These do not drive the robot yet — see §9.

**This is physical machinery.** Every front end above enforces: a human at
the E-stop for any motion, envelope checking, and no automatic retries
after an uncertain result. The safety model is detailed in §7.

---

## 2. Current focus: kinesthetic demonstration & replay (in progress)

The team is currently building a **simple kinesthetic imitation-learning
workflow**: an operator physically guides ("hand-guides") the arm through
a task, and the system records that demonstration so it can be replayed
later on command.

> **What this is not:** this is literal playback of a recorded
> demonstration, not a learned, generalizable policy. The robot does not
> infer new motions, does not adapt to a moved or different object, and
> cannot perform any task it has not been physically demonstrated.
> "Learning" here means *record once, replay the same routine many
> times* — nothing more, for now.

**Initial target routine** — the first end-to-end demonstration this
workflow is being built to capture and replay:

```
Home → Hamilton → Home → Octopi Microscope
```

That is: start at the home pose, visit the Hamilton liquid-handling
station, return home, then move to the Octopi microscope station.
Additional routines/stations are expected to be added the same way, one
recorded demonstration at a time.

### What this builds on

This is a new *capture-and-replay layer*, not a new control stack. It is
designed to sit on top of the same hardened BRCAPI client, envelope
checking, and arrival verification already built for the grab pipeline
(§6.2) — the same foundation the operator console and the standalone
grabber already share. Physically hand-guiding the arm requires it to be
backdrivable or placed in a compliant/teach mode; which controller mode
makes that possible on the S4 is not yet confirmed and should be verified
with the vendor before any live hand-guiding is attempted.

### Status — implemented vs. planned

| Piece | Status |
| --- | --- |
| Recording a hand-guided demonstration on the **physical** arm | **Planned** — not yet in the codebase |
| Replaying a saved demonstration | **Planned** |
| The `Home → Hamilton → Home → Octopi Microscope` routine specifically | **Planned** — target first routine |
| Researcher-facing UI (record / review / run) | **Planned** — see §3 |
| Underlying motion/safety layer (hardened TCP client, envelope checks, arrival verification) | **Already implemented** — reused from §6.2 |
| A related but distinct *browser-driven* demonstration recorder that records dragged poses in the **MuJoCo simulation** | **Already implemented** — see §9; this is a simulation/offline tool, not the physical kinesthetic workflow described here, and the two should not be conflated |

Keep this table current as pieces land. Do not let wording elsewhere in
this document (or in the UI) imply more than what is actually running on
the physical robot.

---

## 3. Planned UI: recording and running demonstrations

This will be a new, **researcher-facing** interface, deliberately simpler
than the existing engineer-oriented operator console (§6.2), which
exposes raw sequence buttons, torque charts, and kinematic debugging
tools. The demonstration UI hides that complexity behind three plain
actions:

1. **Record a demonstration.** The researcher starts a recording, guides
   the arm by hand through the task (a developer/supervisor puts the arm
   into a hand-guidable state beforehand), and stops recording. The
   system saves the full motion as a named routine — e.g. "Home →
   Hamilton → Home → Octopi".
2. **Review saved routines.** A list of previously recorded routines,
   each showing its name, the stations/steps it passes through, and when
   it was recorded. A researcher can select one to inspect — e.g. a step
   list or a preview — before committing to run it.
3. **Start / pause / stop execution.** Large, clear controls to run a
   selected routine: **Start** begins replay, **Pause** holds the arm at
   its current point, **Stop** halts it. The physical E-stop remains the
   authoritative safety control at all times — these are software
   requests, not a substitute for it (see §7; this inherits the "STOP SEQ
   is not an E-stop" rule already documented for the operator console in
   `HANDOVER_OPERATOR_UI.md` §4).

Design intent: a researcher should be able to record, check, and run a
routine without needing to understand kinematics, calibration, or the
BRCAPI protocol — that complexity stays behind the scenes.

### Who maintains what

- **Researchers** use the simple record / review / run UI above.
- **Developers** own and maintain the backend that makes it work — the
  hardened robot control layer, capture/replay logic, calibration, and
  safety guards — and deploy updates to it as needed (bug fixes, new
  station support, new safety rules) without requiring researchers to
  change how they use the UI.

This mirrors the existing split in the project: `operator_ui/` and
`bioyond-s4-mcp/` are already developer-maintained while exposing a
simpler surface (buttons, tool calls) to their respective users. The
kinesthetic workflow's UI is a further simplification aimed at
researchers who are not expected to operate the engineer-facing console.

---

## 4. System architecture

```
                    ┌─────────────────────────────┐
                    │   Bioyond S4 controller      │
                    │   BRCAPI (TCP/JSON, newline- │
                    │   framed), 192.168.201.220   │
                    │   :56788 — ONE client only   │
                    └───────────┬─────────────────┘
                                │  mutually exclusive
          ┌─────────────────────┼─────────────────────┐
          │                     │                      │
 ┌────────▼────────┐   ┌────────▼─────────┐   ┌────────▼────────┐
 │ bioyond-s4-mcp/  │   │  operator_ui/    │   │  Bioyond Works  │
 │ (MCP server,     │   │  (Flask console, │   │  (vendor app,   │
 │  agent-driven)   │   │  human-driven)   │   │  publishing /   │
 │                  │   │                  │   │  taught jobs)   │
 │ server.py tools  │   │ app.py routes -> │   └─────────────────┘
 │  -> robot.py     │   │  robot_service.py│
 │  (hardened       │   │  (hardened       │
 │   TCP client)    │   │   TCP client,    │
 └────────┬─────────┘   │   port of the    │
          │             │   MCP logic +    │
          │             │   drop-recovery) │
          │             └────────┬─────────┘
          │                      │
          │        ┌─────────────┴─────────────┐
          │        │        sequences.py        │
          │        │  (find/align/descend/grip  │
          │        │   as stoppable, logged      │
          │        │   background sequences;     │
          │        │   also imported headlessly   │
          │        │   by grab_aruco.py)          │
          │        └─────────────┬─────────────┘
          │                      │
 ┌────────▼──────────────────────▼─────────────────────────┐
 │               grab_skill/  (vision + grasp math)         │
 │  aruco_world.py (solver) · aruco_detect.py · mcp_teach.py│
 │  torque_probe.py · anchors.py · fit_eye_cam.py           │
 │  calibration.json / anchors.json  <-- persisted constants│
 └───────────┬────────────────────────────────────┬────────┘
             │                                     │
   ┌─────────▼─────────┐                 ┌─────────▼─────────┐
   │ GigE eye-in-hand   │                 │ 2× Arducam context │
   │ camera (precision, │                 │ cameras (rough     │
   │ mounted on Z-      │                 │ localization only, │
   │ carriage)          │                 │ no local CV —agent │
   │ ~13-15 px/mm       │                 │ reads frames)      │
   └────────────────────┘                 └─────────────────────┘
```

The planned kinesthetic record/replay layer (§2) is expected to attach
alongside `sequences.py`, reusing `robot_service.py`'s hardened client
rather than talking to the controller directly — it is not shown as a
separate box above because its exact integration point is not yet built.

Everything downstream of the three existing front ends funnels through
the same `grab_skill` vision/kinematics math and the same persisted
calibration files — there is exactly **one** implementation of "where is
the object" and "where must the TCP go", shared by the agent, the human
console, and the standalone script. This is the central design
invariant: **no front-end-specific math, no hardcoded poses.**

### Mutual exclusion

The controller accepts exactly one TCP client, and the GigE camera exactly
one grab controller (MVS SDK). The MCP server, the operator console, and
Bioyond Works are therefore mutually exclusive for robot control; the MVS
live view and any capture tool are mutually exclusive for the camera.
Every README in this repo repeats this because it is the single most
common "nothing is happening" bug.

---

## 5. Hardware inventory

| Device | Role | Interface | Notes |
| --- | --- | --- | --- |
| Bioyond LabGenius S4 | the arm | BRCAPI TCP/JSON, 192.168.201.220:56788 | J1 vertical ram, J2/J3 planar links, J4 wrist yaw, E1 gripper, E2 rotator (unused) |
| GigE JHEM600GM-HM | eye-in-hand precision camera | GigE Vision / MVS SDK, 192.168.201.89 | Mono 3072×2048, mounted on the Z-carriage, ~13-15 px/mm at deck depth — the precision sensor for all grasp solving |
| 2× Arducam B0478 | context / rough-localization cameras | USB3, OpenCV capture | Identical device name — enumeration order can swap after reboot/replug, verify by scene content; no local object detection (agent reads the raw frame by design) |
| Intel RealSense D405 | depth sensing (experimental) | USB3, librealsense | Live color/depth/point-cloud tested at 640×480 ~30 fps; camera-to-arm calibration not yet done |
| E-stop | physical safety control | hardware | Authoritative; software never substitutes for it |

---

## 6. Software components

| Path | What it is | Entry point |
| --- | --- | --- |
| `bioyond-s4-mcp/` | MCP server exposing the robot + cameras as tools | `server.py` (registered via `.mcp.json`) |
| `operator_ui/` | Flask human-in-the-loop console | `py operator_ui/app.py` → `:5002` |
| `Pick and Hold/` | Canonical per-stage implementations (Calibration/Align/Descend/Grip/Hold); `operator_ui` imports from here | see `Pick and Hold/README.md` |
| `grab_skill/` | Vision solvers, kinematics, torque probing, calibration data, and the standalone grabber | `grab_aruco.py` |
| `.claude/skills/` | Agent-facing procedural knowledge (when/how to run a grab) | `grab-object/SKILL.md`, `aruco-grab/SKILL.md` |
| `camera_gui/` | Standalone 3-camera viewer with box-annotate + ask-Claude chat | `py camera_gui/app.py` → `:5001` |
| `mujoco_sim/` | Offline physics prototype / demonstration recorder (not a digital twin) | `open_project.py` |
| `arducam/` | Realtime SAM2/SAM3/DINOv3/YOLO detection on the context cameras (exploratory, not wired into grasping) | `realtime_*.py` |
| `Vision_context/` | Vendor Vision SDK + teach demo (reference only; `grab_skill/mcp_teach.py` is an exact Python port of its math) | — |
| `Bioyond_S4_Agent_Context_Pack/` | Vendor manuals, BRCAPI protocol spec, Lua sources, background | `01_Project_Context/AGENT_CONTEXT.md` |
| `Config/` | Controller-side logging config (`LogConfig.json`) | — |
| `main*.bin` | Controller programs (customer original + host-point extension + torque-telemetry variant) | published via Bioyond Works |

### 6.1 `bioyond-s4-mcp/` (agent front end)

- `server.py` — MCP tool definitions (connection/mode/enable control,
  Cartesian/joint motion, taught jobs, camera capture, raw BRCAPI
  passthrough). Tools that bypass guards or clear faults require
  `operator_confirmed=true` from a human — the server enforces this, an
  agent must never set it unprompted.
- `robot.py` — hardened BRCAPI client: frame parsing (fragmented TCP
  frames), unit conversion (controller reports meters/radians, commands
  use mm/degrees; float params come back as strings), envelope checking.
- `hikcam.py` / `vision.py` — GigE and Arducam capture.
- `tests/test_offline.py` — runs the tool surface against a **fake
  controller** that emulates the real one's quirks (fragmented frames,
  string params, -1-rejection path). No robot needed; keep green.
- Does **not** yet auto-recover a mid-command TCP drop the way
  `operator_ui/robot_service.py` does (open item — see §10).

### 6.2 `operator_ui/` (human front end)

```
app.py             Flask routes, Runner instance, TorqueRecorder thread,
                    points/roles/motion-order store (points.json)
robot_service.py   hardened robot layer: preflight guards, envelope box,
                    kinematic reach guard (base-centred IK), ARRIVAL
                    VERIFICATION (pose_after must match command),
                    MID-COMMAND DROP RECOVERY (reconnect -> settle ->
                    judge by pose; never resends), safe program start,
                    gripper jobs + torque report
sequences.py       Runner (one background sequence thread + log + STOP
                    flag) + all sequences + exact planar IK + travel-leg
                    order parser
camera_service.py  GigE frames (fresh-snap for vision, cached for view)
aruco.py / teach.py  thin wrappers over grab_skill solvers
static/index.html  the whole frontend (vanilla JS, Console tab + Points/
                    Trajectory tab, pollers)
```

One motion lock serializes all robot access inside the console; one
sequence runs at a time. `grab_skill/grab_aruco.py` imports
`robot_service` and `sequences` directly, so it inherits arrival
verification and drop recovery "for free" — this is why the standalone
grabber is in `grab_skill/` but depends on `operator_ui/`, not the other
way around.

Sequences (`sequences.py`), one per pipeline stage: `seq_find_disk`,
`seq_find_aruco`, `seq_align`, `seq_descend`, `seq_grip`,
`seq_generate_anchor`, `seq_calibrate_camera`, `seq_calibrate_aruco`,
`seq_workflow` (multi-point pick→place→home). Each is a stoppable,
logged background job — see `HANDOVER_OPERATOR_UI.md` §3 for the
per-sequence algorithm.

### 6.3 `Pick and Hold/` (canonical stage implementations)

The extracted, single-source-of-truth implementation of each pipeline
stage; `operator_ui/pick_and_hold` is an import bridge (the folder name
has a space, hence the bridge) and `sequences.py` delegates to it for the
three extracted motion functions:

| Stage | File | Status |
| --- | --- | --- |
| Calibration | `Calibration/fast_disk.py` | Complete two-disk algorithm — loop, vision/pose math, planning, guards, convergence |
| Align | `Align/motion.py` | Existing guarded hover / wrist rotation / XY alignment (live) |
| Align | `Align/ic.py`, `Align/references.py` | New inverse-compositional (Lucas–Kanade) image alignment — **measurement/preview only, does not yet drive robot corrections** |
| Descend | `Descend/motion.py` | Torque-guarded approach/descent (live) |
| Grip | `Grip/motion.py` | Torque + position-stall grip confirmation (live) |
| Hold | `Hold/pickup.py` | Supervised lift verification (live, needs its commissioned ArUco marker) |

### 6.4 `grab_skill/` (vision + grasp math — the shared core)

| File | Role |
| --- | --- |
| `aruco_world.py` | **The solver.** Marker world pose (XY/Z/yaw) → claw-arm-compensated grab candidates (TCP + wrist Rz) → grip Z. All four approach candidates (2 clamp axes × 2 wrist sides), feasibility by exact kinematics. |
| `aruco_detect.py` | Raw ArUco detection + PnP (vendor intrinsics; must undistort before PnP). |
| `mcp_teach.py` | SDK-exact port of Bioyond's own vendor Vision SDK teach (detect → trigger config → image↔robot transform → convergence). `py mcp_teach.py test` must print ALL PASS before trusting it. |
| `sdk_pose.py` / `sdk_detect.py` | Vendor pose math (Rz·Ry·Rx Euler) and HoughCircles detector, ported exactly. |
| `circles.py` | Generic circle-pair detector, more permissive than the SDK's — useful for first sighting. |
| `torque_probe.py` | Baseline/band computation for torque-based contact detection. |
| `anchors.py`, `rederive_claw_arm.py` | Ground-truth anchor management and the self-heal re-derivation (§8). |
| `fit_eye_cam.py` | Offline least-squares camera-mount fit from a hand-edited capture table. |
| `grab_aruco.py` | The standalone end-to-end CLI grabber (§6.6). |
| `calibration.json`, `anchors.json` | Persisted constants — see §8. |

### 6.5 Agent skills (`.claude/skills/`)

Procedural knowledge for an LLM agent, loaded by name, not code:

- `grab-object/SKILL.md` — the founding torque-guided pipeline (context
  cams → eye cam → guarded descent → grip) for untaught objects.
- `aruco-grab/SKILL.md` — the anchor-free ArUco pipeline for marker-tagged
  objects at arbitrary positions. Both encode the full safety doctrine
  inline and must be read before any grab task.

### 6.6 Standalone grabber

`py grab_skill/grab_aruco.py [--hold] [--hover 300] [--open 28]
[--no-lift] [--ip …]` — full pipeline with no browser/MCP: stamp gate →
preflight → find (center-view, 2-agree, multi-viewpoint) → exact-IK
candidate pick → J4-planned align → torque-guarded descent → torque-
stalled grip with span sanity → slow lift + held check. Refuses to run
if the calibration stamps show the claw-arm constants predate the
current camera fit (§8).

---

## 7. Safety model

Non-negotiable, enforced at the `robot_service.py` / `server.py` layer
wherever possible, and restated in every skill/handover doc because
violating it has physically damaged nothing *only* because it was
followed:

1. **A human is at the E-stop for any motion.** `operator_confirmed=true`
   is passed only after a *fresh* human say-so, never cached per session.
2. **A motion timeout or mid-command TCP drop means unknown physical
   state.** Never resend. Reconnect, re-query `get_status` +
   `get_cartesian_pose`, and judge by the resulting pose — the Lua
   program keeps executing after the socket dies, so the move usually did
   complete, but this must be verified, not assumed.
3. **Stale acks are real.** A move can report success (`value:1`) while
   the controller actually faulted mid-path. Success = pose-after matches
   the commanded target, nothing else.
4. **Torque band = tripwire, not a debate.** First breach stops the
   descent immediately; retreat 0.5–1 mm and discriminate contact
   (unloads on retreat) from drift (follows the trend). Never press
   deeper to confirm.
5. **Never grip at a blocked depth**, and **never stop/start the Lua
   program while holding an object** (program start re-zeroes E1, which
   slams the plates shut).
6. **Speed caps**: travel ≤30, approach ≤15–20, probing 5, lift 8–10.
7. **`joint` interpolation only for zero-translation rotations** — its
   Cartesian arc is unpredictable; all translations use `linear`.
8. **The workspace envelope is a placeholder by default** — it does not
   match the real working area and must be set for the task before real
   motion (`set_workspace_envelope`, operator-confirmed).

These rules apply equally to the planned kinesthetic workflow (§2):
recording still happens with a human controlling the arm directly, and
replay must inherit the same envelope/arrival-verification/stop
guarantees as every other motion path in this project — it does not get
a lighter safety bar just because it is "simple" from a researcher's
point of view.

See `CLAUDE.md` for the full enforced tool-level contract and
`HANDOVER_MCP_SKILLS.md` §3/§11 for the complete, dated list of rules and
the live incidents that produced each one.

---

## 8. Calibration & data architecture

**Design principle: nothing about a specific arm, camera mount, claw, or
object is hardcoded in code.** It is all measured at runtime and persisted
as data, so the same code ports to a different arm/camera/claw by
re-running calibration flows, not by editing scripts (see the "porting to
a new arm" recipe in `aruco-grab/SKILL.md`).

| File | Contents |
| --- | --- |
| `grab_skill/calibration.json` | `eye_cam_fit` (camera mount model + a **`fitted` stamp**), `claw_arm_tool_mm` + **`claw_arm_model_version` stamp**, `wrist_rel_deg`, `z_touch_offset_mm` + `safety_margin_mm`, per-marker-id `marker_offsets` (disk-center offset, relative yaw, spans, optional recessed-marker `grip_z_offset_mm`), and a full fit history |
| `grab_skill/anchors.json` | Ground-truth anchors: rows of (marker pixel, optical distance, capture pose, verified grab TCP/Rz) |
| `operator_ui/robot_params.json` | Fitted planar kinematic block (base, link lengths, joint offsets), joint limits + margins, claw gap window |
| `operator_ui/envelope.json` | Soft Cartesian safety box + enabled flag |
| `operator_ui/torque_config.json` | Operator-picked descent torque band |
| `operator_ui/points.json` | Saved points, roles (start/end/home), motion order |

**The self-heal mechanism**: `claw_arm_tool_mm` and `wrist_rel_deg` are
derived *through* the current camera model (they come from solving the
camera's own view of known anchors). Any camera refit silently
invalidates them — this caused a real 7.7 mm miss once. The fix is
mechanical, not procedural: every value carries a model-version stamp,
`anchors.py::derive_and_save()` re-derives the claw constants from the
stored anchors under the *current* camera model, and `grab_aruco.py`
**refuses to run** if the stamps mismatch. The console's "Calibrate
camera" button runs the re-derivation automatically; the CLI equivalent
is `py grab_skill/rederive_claw_arm.py --save`.

Model health check: anchors agreeing with each other validates
arm-vs-model *consistency*, not the model's absolute accuracy (a
single-viewpoint common-mode bias can pass that check while still being
wrong) — true model health comes from the **center-view rule** and
multi-viewpoint spread check described in `aruco-grab/SKILL.md`.

---

## 9. Perception subsystems beyond the core grasp pipeline

These are real, working pieces of software, but **none of them currently
drive a robot motion** — they are either tooling, exploration, or
precursors to future grasp pipelines. Treat this status as current only
as of this document's date; check each subsystem's own README for
updates.

| Subsystem | What works | What doesn't (yet) |
| --- | --- | --- |
| **IC alignment** (`Pick and Hold/Align/ic.py`) | Inverse-compositional Lucas–Kanade image matching, comparison preview | Correctly aligned reference images and live validation; does not drive robot corrections |
| **RealSense D405** (`operator_ui/realsense_*`) | Live color/depth/point-cloud (Viser 3D), 640×480 @ ~30 fps | Camera-to-arm calibration |
| **Depth Anything V2 / Haiku scene description** (`operator_ui/depth_*`, `train_depth.py`) | Relative-depth inference + scene description tooling | Metric-depth training (needs independently measured ground truth — neither the model's own output nor Haiku provides it); autonomous picking from depth is not validated |
| **MuJoCo** (`mujoco_sim/`) | Measured-scene layout, interactive viewer, demonstration recording/replay, contact simulation with a documented set of passing regression checks | Explicitly **not** a calibrated digital twin, collision-safety certificate, trained policy, or hardware motion executor — a hardware rehearsal of a MuJoCo-planned route already faulted (axis-4 collision, see `mujoco_sim/README.md`). Its browser-based demonstration recorder (dragging the arm in a 3D view) is a *simulation* tool, distinct from the physical kinesthetic hand-guiding workflow in §2. |
| **Arducam realtime detection** (`arducam/realtime_*.py`) | SAM2/SAM3/DINOv3 segmentation, YOLO, on the context camera feed | Not wired into any grasp pipeline — the grasp pipelines deliberately use agent-read frames instead of local CV, per standing operator preference |

---

## 10. Known open items / design debt

From the last recorded handovers (dated — check staleness against
current git history before relying on these):

1. **The kinesthetic demonstration/replay workflow (§2) is newly started
   and has no implementation yet** — recording, replay, the researcher
   UI (§3), and the hand-guidable/compliant controller mode it depends on
   are all open design and implementation work.
2. **MCP server lacks the operator console's drop-recovery.** Mid-command
   drops are handled manually (reconnect → verify pose) rather than
   automatically. Porting `robot_service.py`'s recovery logic into
   `bioyond-s4-mcp/robot.py` would unify the two front ends' robustness.
3. **Workflow motion order is global, not per-leg** — a natural extension
   once multi-stop routes (>3 roles) are needed.
4. **The claw-window span check is warning-only** (operator decision, not
   a bug) — revisit if unattended/unsupervised operation is ever wanted.
5. **Two-body assemblies** (e.g. an object riding an adapter plate inside
   a pan) are not modeled as a first-class concept — each body currently
   needs its own marker/id to be unambiguous.
6. **IC alignment** needs correctly-aligned reference images and live
   validation before it can replace or augment `seq_align`.
7. See `HANDOVER_MCP_SKILLS.md` §13 and `HANDOVER_OPERATOR_UI.md` §9 for
   the full, dated lists, including the physical arm state at last
   handover (always re-verify against live `get_status` before assuming
   anything about physical state from a doc).

---

## 11. Testing

| Suite | Scope | Run from | Robot needed? |
| --- | --- | --- | --- |
| `bioyond-s4-mcp/tests/test_offline.py` | MCP tool surface against a fake controller (fragmented frames, string params, -1-rejection path) | repo root | No |
| `operator_ui/tests/test_offline.py` | 96 checks: service guards, arrival verification, IK regression on live pose pairs, anchors derive/gate/restamp, 4-way grab candidates, sequences, a full simulated workflow, vendor-exact anchor loop, camera-fit recovery on synthetic scenes | `operator_ui/` | No |
| `operator_ui/tests/test_ic*.py`, `test_fast_disk.py`, `test_alignment.py`, `test_pickup.py`, `test_transfer.py` | Per-stage unit tests for the `Pick and Hold/` implementations | repo root, `py -B -m unittest discover -s operator_ui/tests -p '<pattern>' -v` | No |
| `mujoco_sim/test_contact_sim.py`, `test_measured_scene.py` | FK, jaw aperture, retiming, friction-only grasp/release, scene geometry regression | `mujoco_sim/` | No |

The fake-controller suites are **the contract** for the BRCAPI quirks
(meters/radians pose query, string float params, `setSysParaF` index
limits, -1 = rejected job). Any protocol change must update the fake
controller and keep both offline suites green; add a regression test for
every new live lesson learned. When the kinesthetic workflow (§2) gains
real recording/replay code, it should get the same treatment: an offline
test suite that does not require the physical robot.

---

## 12. Directory map (annotated)

```
.mcp.json                   MCP server registration (IP, speed caps, envelope env vars)
CLAUDE.md                   Agent operational contract — read first for any live robot work
README.md                   Install/run instructions + progress tracker
DESIGN.md                   This document
HANDOVER_MCP_SKILLS.md      Robot layer, kinematics, calibration architecture, hard-won lessons
HANDOVER_OPERATOR_UI.md     Flask console architecture, sequences, recipes, test suite
main.bin                    Customer's original controller program (never delete)
main_hostpoint.bin          Published: original + host-point Cartesian extension
main_hostpoint_trq.bin      Published: + per-joint torque telemetry (needed for torque guarding)

bioyond-s4-mcp/             MCP server (agent front end)
operator_ui/                Flask console (human front end) + depth/RealSense tooling
Pick and Hold/              Canonical per-stage motion implementations
grab_skill/                 Vision solvers, kinematics, calibration data, standalone grabber
.claude/skills/             Agent-facing grab procedures
camera_gui/                 Standalone 3-camera viewer + ask-Claude chat
mujoco_sim/                 Offline physics prototype / demonstration recorder
arducam/                    Realtime SAM/DINO/YOLO detection experiments
Vision_context/             Vendor Vision SDK + teach demo (reference)
Bioyond_S4_Agent_Context_Pack/  Vendor manuals, protocol spec, Lua sources
Config/                     Controller-side logging config
tools/realsense/            Vendor RealSense Viewer binary
models/                     Downloaded model weights (YOLO, Depth Anything) — gitignored
third_party/                Vendored dependencies (Depth-Anything-V2, mjviser) — gitignored
```

(No directory for the kinesthetic demonstration/replay workflow exists
yet — it will be added here once its code lands.)

---

## 13. Where to go deeper

| Question | Read |
| --- | --- |
| "What's the kinesthetic demonstration/replay workflow and what's its status?" | §2–§3 of this document |
| "How do I bring the robot up for a session?" | `CLAUDE.md` §Quick start |
| "What exactly can go wrong, and what did it cost to learn?" | `HANDOVER_MCP_SKILLS.md` §11, `aruco-grab/SKILL.md` "Known traps" |
| "What's the exact math for a grab candidate?" | `grab_skill/aruco_world.py`, `aruco-grab/SKILL.md` §"The model" |
| "How do I calibrate a new object / new camera / new arm?" | `aruco-grab/SKILL.md` §"Per-ID disk calibration" / "Porting to a new arm" |
| "What does the console's UI actually do button-by-button?" | `HANDOVER_OPERATOR_UI.md` §4-5 |
| "What's the BRCAPI wire protocol?" | `Bioyond_S4_Agent_Context_Pack/02_Protocol/` |
| "What's actually done vs. in progress?" | `README.md` §Progress so far |
