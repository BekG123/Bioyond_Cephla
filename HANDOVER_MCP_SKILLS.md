# Handover — S4 Robot: MCP Server, Skills & Autonomous Grabbing

Audience: the next engineer/agent continuing this project. Companion doc:
`HANDOVER_OPERATOR_UI.md` (the human-in-the-loop console). Everything
below was measured/validated on the live robot; dates given so you can
judge staleness. Read `CLAUDE.md` first — it is the operational contract.

---

## 1. Mission & status (as of 2026-07-28)

Goal: reliably grab ArUco-marked objects at arbitrary deck positions with
a Bioyond LabGenius S4 4-axis SCARA, through (a) an MCP server for agents,
(b) a Flask operator console, (c) a standalone Python program.

Status: the full pipeline (find → align → torque-guarded descend → grip →
lift) is live-validated multiple times, including one fully autonomous
run of `grab_skill/grab_aruco.py` (drop-recovery fired twice mid-run and
continued; grip stall measured the object span; lift verified). The last
session ended mid-grab (see §13 Physical state).

## 2. Hardware & connection facts

- Robot: Bioyond LabGenius S4, joints J1 (vertical ram), J2/J3 (planar
  links), J4 (wrist yaw). External axes E1 (gripper) + E2 (rotator; E2
  effectively unused). Controller speaks **BRCAPI** (TCP/JSON,
  newline-framed) at **192.168.201.220:56788**.
- **ONE TCP client at a time**: the MCP server, the operator console, and
  Bioyond Works are mutually exclusive. `ConnectionRefused` = someone
  else is connected.
- Eye-in-hand camera: GigE **JHEM600GM-HM** (mono 3072×2048) at
  192.168.201.89, MVS SDK, ~13-15 px/mm at working depths, ONE grab
  controller at a time (release before MVS client use). Two Arducam
  context cams exist but were unplugged late on 07-28.
- Gripper E1: two comb plates closing along the tool's grip axis.
  `gap_mm ≈ E1 + 60`; E1 28 = fully open (88 mm gap), 0 = closed (60).
  Free torque +150..+195; **gripping = torque < −100 AND position stall
  > 0.15** (saturation ≈ −187). `grip_by_torque` is the preferred close.
- Per-joint torque telemetry: SysVarI 13-16 = J1-J4 normalized torque
  ×1000 — ONLY when **`main_hostpoint_trq.bin`** is the published
  program. If 13-16 read 0, torque guarding is blind: stop and republish.

## 3. Safety doctrine (non-negotiable, learned live)

1. Human at the E-stop for any motion. `operator_confirmed=true` is
   passed only after a FRESH human say-so — never once-per-session.
2. Motion timeout / mid-command connection drop = **unknown physical
   state**: never resend; reconnect → `get_status` + `get_cartesian_pose`
   → judge by POSE. (The Lua keeps executing after the socket dies —
   moves usually completed. Verified repeatedly.)
3. **Stale acks are real**: a move can return success (`value 1`) while
   the controller faulted mid-path (observed: 16 mm + 47° off). Success
   = pose_after matches the command, nothing else.
4. Torque band = tripwire: FIRST breach stops the descent; retreat
   0.5-1 mm and discriminate (contact unloads, drift persists). Never
   press deeper to confirm. J1 is judged against the post-step TREND
   only (stationary J1 is not comparable — direction artifact).
5. Never close the gripper at a blocked depth; never stop/start the Lua
   program while holding (program start re-zeroes E1 = plates slam shut).
6. Speeds: travel ≤30, approach ≤15-20, probing 5, lift 8-10 (slow for
   trays of loose parts).
7. `joint` interpolation ONLY for zero-translation rotations (its
   Cartesian arc is unpredictable); all translations `linear`.
8. In-place rotations sweep the claw's ~191 mm arc — do them at Z ≥ 280
   and mind the swept zone (see §6 claw geometry).

## 4. Controller-side contract

- Published program: **`main_hostpoint_trq.bin`** = customer `main.bin`
  (station jobs) + `mod_HostPoint` + torque telemetry. Never delete
  `main.bin` (root).
- Jobs trigger by writing SysVarI in ONE frame: `0=DeviceID, 1-3=pos
  selectors, 4=MoveType, 5=ObjType, 6=ClampMode`. Lua polls at 100 ms,
  runs the job, replies via SysOutVar (`{index:1, value:1}` = done,
  `-1` = rejected → wrong pattern or program not published).
- Host-point (device 21): floats `0=X 1=Y 2=Z 3=Rz 4=speed 5=blend
  6=E1` (mm/deg); MoveType `1=MoveL 2=MoveJ 3=gripper 4=MoveAbsJ
  5=torque-report (no motion)`.
- Publishing = Bioyond Works: Import bin into Offline Project →
  **Publish Offline Project to Controller**. Afterwards the controller
  resets to manual/disabled/stopped; a paused program that is *resumed*
  runs OLD code — always stop→start.
- Known quirks: pose query returns METERS+RADIANS (only ever use the
  server's `pose_mm`/`rotation_deg`); `getSysParaF/I` return strings;
  `setSysParaF` accepts indexes 0-18 only; manual→auto mode switch DROPS
  the servo enable (then `remoteStart` fails with controller error 8
  until re-enabled); TCP drops before/during commands are ROUTINE.

## 5. MCP server (`bioyond-s4-mcp/`)

`server.py` (tools) + `robot.py` (hardened client) + `hikcam.py` (GigE)
+ `tests/test_offline.py` (fake controller — run `py tests/test_offline.py`).
Registered via `.mcp.json` (IP, speed caps, envelope env vars).
Tool list + one-line semantics: see the table in `CLAUDE.md`. Notes:

- `move_to_cartesian` is envelope-checked server-side (default envelope
  is a PLACEHOLDER — set a real task box first).
- The MCP server does NOT yet auto-recover mid-command drops (the
  operator console's `robot_service.py` does — port it if desired).
  Manual doctrine: reconnect → verify pose → continue.
- `gige_capture(grid=false)` for detection work (grid overlay breaks it).

## 6. Measured machine truth (all live-derived; do not guess)

**Planar kinematics (fitted 2026-07-28, 0.00 mm residual on 8 poses):**
`P = base + 200·e^{i·J2} + 200·e^{i·(J2+J3+180°)}`, **base = (126, 0)**.
The world origin is NOT the rotation center. Consequences:
- Reach limit = circle around BASE: |P−base| ≤ 400 absolute; use ≤385
  (J4 cannot track the wrist near full extension → fault 3570; observed
  at a target 3.6 mm past 400).
- **J2 soft limit −95°** (fault 3571 froze J2 at −95.10; the exact IK
  reproduces that stop to the decimal). Guard: predicted J2 ≥ −93.
- J4 soft limit ±205 hard (faults ≈ ±220), prefer ±150 headroom.
  In-place rotation moves J4 by exactly the delta; translation shifts it
  by −Δ(J2+J3). Plan END-state J4; wind ±360 the long way when needed
  (≤90° chunks). IK helpers: `operator_ui/sequences.py::_ik_j2j3`,
  `_reach_block` (params in `operator_ui/robot_params.json`).

**Claw geometry:** the claw midpoint hangs on a bracket arm ≈
**(191.5, 5.6) mm in the tool frame** (192 mm!). `claw_world = TCP +
R(Rz)@claw_arm`; grabs MUST subtract it: `TCP = grab_point −
R(Rz_grab)@claw_arm`. Objects far beyond TCP reach are grabbable via
this overhang (validated at disk reach 536). `wrist_rel ≈ 88.3°` = pure
claw constant (90° − arm angle): `Rz_grab = disk_axis + wrist_rel ± 180`.

**Eye-camera model (fitted 07-25, RMS 0.26 mm, 12 live rows):**
`marker_world = TCP + R(Rz)@cam_arm + R(Rz+yaw_off)@diag(1,mirror)@
(u_scale·u_pnp + tilt·H)`; cam_arm (17.77, 56.77), yaw_off 90.5,
mirror −1, u_scale 1.187, tilt (0.04427, −0.024)/mm, h_scale 1.0501
(marker_z = Z − 32.1 − h_scale·H). Marker size on the current sheet:
**16.553 mm** (nominal "20 mm" printed at ~83% — verify any new sheet
with the two-height check). **Center-view rule**: trust solves only with
the marker near image center; 2 agreeing solves (<2 mm) + a third
viewpoint; spread >3 mm ⇒ recalibrate the camera.

## 7. Calibration data architecture (nothing is hardcoded)

- `grab_skill/calibration.json`: eye_cam_fit (+ **`fitted` stamp**),
  claw_arm_tool_mm + **`claw_arm_model_version` stamp**, wrist_rel_deg,
  z_touch_offset_mm (9.0) + safety_margin_mm (0 — operator's standing
  order: publish true values, the torque guard is the protection),
  marker_offsets per id (dx/dy in MARKER frame — rotation-invariant —
  rel_yaw, spans, optional **grip_z_offset_mm** for recessed markers),
  history (including the reverted bad camera fit of 07-28 21:19).
- `operator_ui/robot_params.json`: kinematic block + limits + claw gap.
- `grab_skill/anchors.json`: **ground-truth anchors** — rows of
  (mark pixel, optical distance H, capture pose, verified grab TCP/Rz).
  `grab_skill/anchors.py::derive_and_save()` re-derives claw arm +
  wrist_rel from them under the CURRENT camera model (≤1 mm agreement
  gate) and restamps. This is the **self-heal**: any camera refit must
  be followed by it (the console's Calibrate camera does it
  automatically; CLI: `py grab_skill/rederive_claw_arm.py --save`).
- **THE STALE-CONSTANT RULE** (cost a 7.7 mm miss live): claw_arm and
  wrist_rel are extracted THROUGH the camera model — any refit
  invalidates them until re-derived. The stamps make this machine-
  checkable; `grab_aruco.py` refuses to run on mismatched stamps.
- Anchor limitation (observed 07-28): anchors at a single viewpoint
  agree with each other even under a WRONG model (common-mode bias) —
  anchor agreement validates arm-vs-model consistency, not the model
  itself. Model health comes from the multi-viewpoint spread check.

## 8. Skills & scripts

- `.claude/skills/grab-object/SKILL.md` — the founding torque-guided
  pipeline (context cams → eye cam → guarded descent → grip). Read for
  the full safety text; still authoritative for untaught objects.
- `.claude/skills/aruco-grab/SKILL.md` — the anchor-free ArUco pipeline:
  procedure, all-four-approach candidates, traps, per-id calibration,
  new-arm porting order, refit chain. **Read before any grab work.**
- `grab_skill/` inventory:
  - `aruco_world.py` — THE solver (`solve IMG X Y Z RZ`): marker world +
    4 grab candidates (2 axes × 2 wrist sides, spans + clampable info,
    feasible = arm-reachability only) + grip_z (per-id override aware).
    Also fit_mount, save_* (stamping), calibrate_disk, marker_offset.
  - `aruco_detect.py` — raw ArUco detection/PnP (vendor intrinsics;
    UNDISTORT before PnP — SDK distortion breaks it otherwise).
  - `mcp_teach.py` — SDK-exact vendor teach port. `py mcp_teach.py test`
    MUST print ALL PASS before trusting it.
  - `sdk_pose.py`, `sdk_detect.py`, `circles.py`, `torque_probe.py` —
    vendor pose math, Hough detector, generic circles, torque bands.
  - `anchors.py`, `rederive_claw_arm.py` — see §7.
  - `fit_eye_cam.py` — offline camera-mount fit from a hand-edited row
    table (the console's auto-calibration supersedes it).
  - `grab_aruco.py` — **the standalone end-to-end grabber** (see §9).
  - `calibration.json`, `anchors.json` — data (§7).

## 9. Standalone grabber

`py grab_skill/grab_aruco.py [--hold] [--hover 300] [--open 28]
[--no-lift] [--ip …]` — full pipeline, no browser/MCP: stamp gate →
preflight (auto+enabled+running, torque telemetry live, envelope armed)
→ find (center-view, 2-agree, multi-viewpoint, XY mean + Z MEDIAN) →
exact-IK candidate pick → J4-planned align → optional `--hold` verdict
stop at grip+20 → torque-guarded descent → torque-stalled grip with
span sanity (stall+60 vs calibrated width) → slow lift + held check.
Requires BOTH the robot TCP and the GigE camera free. Its module
docstring is the distilled algorithm log — read it. It reuses
`operator_ui/robot_service.py` + `sequences.py`, so it inherits arrival
verification and drop recovery.

## 10. Object registry (current)

- **id 3 = black ring tray** (marker recycled from an older slide — the
  id belongs to the OBJECT, not the sticker!). Spans ~104.7 × 70.1
  (clamp the 70 width; length exceeds the 88 mm gap). Offset (0.81,
  −0.32) mm marker-frame, rel_yaw 179.76 (recal 07-28 late, on the deck,
  good model). **The marker lies on the LOOSE RING PILE** — its plane
  moves mm-scale in Z and XY when the tray is handled ⇒ (a) recommend
  gluing the marker to the rigid rim/frame, (b) grip depth belongs to
  the RIGID stack, not the marker: on the pan+plate stack grip TCP ≈ 51
  (measured twice); on the bare deck let the guard find the floor.
  `grip_z_offset_mm` currently ABSENT (deck default +9 + guard).
- The tray usually rides a grey adapter plate (~105 × 89) inside a metal
  pan on the SE platform — a TWO-BODY assembly: earlier grips actually
  clamped the PLATE (span 85.1). Be explicit about which body you grab.
- Vendor calibration disk/board: taught configs in
  `Vision_context/...VisionServer/Locator/Config/` — used by
  mcp_teach and Generate-anchor.

## 11. Hard-won lessons (each cost real debugging — do not relearn)

1. Claw ≠ TCP (192 mm arm) — the founding bug.
2. Stale constants after camera refit (7.7 mm miss) → stamps + anchors.
3. Stale acks / drops → arrival verification + settle-and-judge-by-pose.
4. The 3-pose kinematic fit was a phantom (narrow sector) → fit with the
   base offset over WELL-SPREAD poses only; the true model is exact.
5. Origin-centered reach guards are wrong — the base sits at (126, 0).
6. Off-center/off-band solves bias mm-scale → center-view rule.
7. Marker print scale ≠ nominal → two-height check (16.553 here).
8. J1 stationary torque ≠ post-step torque → trend rule.
9. Camera calibration with the target on LOOSE CONTENTS gets poisoned
   (h_scale −0.0099 observed) → the marker must be rigidly FIXED during
   the 12-pose drive; garbage-but-under-gate RMS is possible (1.73) —
   compare against the 0.26 heritage before trusting.
10. Marker on loose contents = drifting reference (Z and XY).
11. Two markers / reflections: sightings ~190 mm apart = one is not
    your object.
12. Manual→auto drops the enable; program start needs enable first.
13. E1 zeroes on program start — never restart while holding.

## 12. Tests

- `operator_ui/tests/test_offline.py` — **96 checks**, no robot needed
  (fake controller): kinematics IK regression on live poses, guards,
  arrival verification, anchors, 4-way candidates, per-id depth,
  sequences incl. a full simulated workflow, vendor-exact anchor loop.
  Run from `operator_ui/`: `py tests/test_offline.py`.
- `bioyond-s4-mcp/tests/test_offline.py` — MCP server suite.
- Keep both green; the suites are the contract.

## 13. Physical state at handover + open items

- Arm: paused mid-grab at TCP **(317.43, −325.78, Z 63.2, Rz 86.55)** —
  the south approach over the ring tray on the DECK at grab point
  (323.44, −134.46) — **claw OPEN at 28**, descent baseline half-taken.
  Park it (lift to Z ≥ 280, close claw) before anything else.
- The controller connection was held by another client at handover time.
- Open items:
  1. Finish/redo the deck grab (3-viewpoint solve is locked, spread
     0.22 mm; target above).
  2. Glue the marker to the tray RIM (rigid) — removes the biggest
     remaining error source.
  3. Optional: port the console's drop-recovery into the MCP server.
  4. Optional: per-leg motion orders (workflow currently one global).
  5. The two-body assembly (plate vs tray) deserves its own marker/id.
