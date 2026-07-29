# Bioyond S4 Robot Cell — Agent Guide

This workspace controls a **Bioyond LabGenius S4** 4-axis lab robot (J1–J4,
E1 gripper, E2 rotator) through the **`bioyond-s4` MCP server** registered in
`.mcp.json`. The server talks BRCAPI (TCP/JSON, newline-framed) to the
controller at **192.168.201.220:56788**. Only ONE raw TCP client can be
connected at a time — disconnect before someone uses Bioyond Works' raw
connection, and vice versa.

**This is physical machinery.** A human must be present with the E-stop for
any motion. Everything below has been verified against the live robot on
2026-07-18 (a +20 mm Z MoveL executed with 0.000 mm lateral drift).

## Quick start (session bring-up)

1. `connect` → performs no motion, no enabling, no error clearing.
2. `get_status` → check: no errors, system state not `init`.
3. `switch_mode("auto")` if in manual.
4. `enable_robot(operator_confirmed=true)` — only after the human confirms
   the cell is clear.
5. `start_program` — if the program was `paused`, prefer `stop_program` then
   `start_program` so main() runs fresh. Program start commands no motion.
6. Wait until `get_status` shows `lua_app_initialized: true`.
7. Query freely; move deliberately.

## Tools

| Tool | Notes |
| --- | --- |
| `get_status` / `get_robot_errors` | full state; error codes 3611/3608=E-stop, 3873=collision |
| `get_cartesian_pose` | returns `pose_mm` (mm, T0/U0) — use this; raw values are meters |
| `get_joint_positions` | J1–J4 (controller reports no external axes even though E1/E2 exist) |
| `move_to_cartesian(x,y,z,rz,speed,interpolation)` | mm / degrees; envelope-checked; `linear`=MoveL, `joint`=MoveJ; speed is Lua MoveL scale (~mm/s), default 50, cap 200 |
| `move_gripper(e1_position)` | arm stays still; **28 = open**; returns torque report + `grip_detected`. **The gripper is the pronged RACK on the tool**: two comb plates that clamp together along the tool's grip axis (≈ the side camera's depth direction at Rz=-32°); E1 = plate gap in mm. Objects are grabbed by placing them between the plates. Free torque baseline is POSITIVE +150..+195; gripping = torque < -100 AND reported position stalls > 0.15 above command (saturates ≈ -187). Test object stalls at 23.34; grip it with cmd ≈ 23.0 |
| `gripper_status()` | E1 position + torque without moving |
| `grip_by_torque(torque_threshold=-100)` | **preferred grab method**: opens to 28, closes in 0.1 steps reading torque each step, stops at the threshold — needs no prior object width; reopens automatically if nothing is gripped by the floor. Release with `move_gripper(28)` |
| `grip_with_force_limit(e1, force)` | force-limited close (MoveExtJWithForce); force units uncalibrated — prefer move_gripper with the stall heuristic |
| `move_joints(j1..j4, operator_confirmed)` | MoveAbsJ; bypasses envelope → needs human confirmation |
| `go_home(operator_confirmed)` | taught homing job (device 3) — large fast motion |
| `run_station_job(device_id, action, ...)` | taught pick/place: 11=P1, 12=Squid, 13=Scale, 14=FluidicsSystem, 15=Lid, 9998, 9999; `action` = pick/place |
| `run_lua_job(sys_var_values, ...)` | raw var patterns (stack: `{0:1,1:col,2:level,...}`, scan: `{0:2}`) |
| `set_workspace_envelope(..., operator_confirmed)` | adjust the Cartesian safety box at runtime |
| `enable_robot` / `disable_robot` / `clear_errors` / `switch_mode` / `start_program` / `stop_program` | state control; enable & clear-errors need `operator_confirmed=true` |
| `read_system_values` / `raw_brcapi` | debugging (query-only) |
| `camera_capture(grid=true)` | grab a frame from the Arducam (1920×1080) with a labeled 100 px coordinate grid — **Read the returned file and locate objects with your own vision** (no local detection, by operator preference) |
| `camera_inspect_region(cx, cy, size)` | 3× zoomed crop around a point, fine 20 px grid in full-frame coordinates — use to refine a pixel estimate before moving |
| `camera_release` | free the camera for other apps |
| `camera2_capture` / `camera2_inspect_region` / `camera2_release` | SECOND Arducam (identical device name, ordinal 1 in enumeration). Enumeration order of the two identical Arducams can swap after reboot/replug — always verify by scene content which camera you're looking through |
| `gige_capture(grid=true)` | GigE JHEM600GM-HM (mono, 3072×2048) at 192.168.201.89 — **EYE-IN-HAND: mounted on the Z-carriage looking down at the deck**, ~13 px/mm at deck depth; scene moves with the arm (X+ → image-down, Y+ → image up-right, Z+ → zoom-out). Close the MVS live view first (one controller) |
| `gige_inspect_region(cx, cy, size)` | 3× zoom crop of the GigE view, fine grid in full-frame coordinates |
| `gige_release` | give the GigE camera back to the MVS client |
| `gige_list_devices` | enumerate GigE cameras (works even while MVS holds them) |

**Verified units**: pose query returns meters + RADIANS; motion commands take
mm + DEGREES. `get_cartesian_pose` returns both `pose_mm` and `rotation_deg` —
only ever feed `rotation_deg` values back into moves, never `pose_raw`.

**Visual DOF map** (calibrated 2026-07-19): side camera (`camera2_capture`)
sees Z+ as up ~4.5 px/mm, Y+ as right ~2.8 px/mm, X+ nearly depth (~1 px/mm);
the GigE eye-in-hand camera is the precision sensor (~13 px/mm).

### Visual pick workflow (agent-driven)

1. `camera_capture` → Read the image, find the target, estimate its pixel
   position from the grid; verify with `camera_inspect_region`.
2. Calibrate image↔robot mapping: at safe height, make a small known move
   (e.g. ±5 mm X), re-capture, measure the pixel shift of the gripper (or a
   feature on it); repeat for Y. This gives px-per-mm in both axes.
3. Approach in small envelope-checked `move_to_cartesian` steps, re-capturing
   and re-estimating after each step (never one big open-loop jump).
4. Grip: `move_gripper(6.5)` to open, descend stepwise, `move_gripper(3)` to
   close, lift, and re-capture to visually confirm the object moved with the
   gripper (the controller reports no gripper feedback).
5. All motion rules above still apply — envelope, low speed, human present.

## Safety rules (non-negotiable)

- Never clear errors or enable without explicit human confirmation — the
  tools enforce `operator_confirmed=true`, don't pass it on your own.
- A motion timeout means **unknown physical state**: never resend; re-query
  `get_status` + `get_cartesian_pose` first.
- Move in small steps at default speed. For a first-move sanity check,
  clamp the envelope tightly around the current pose (±2 mm) so only the
  intended step is physically possible.
- The default envelope (X 200–450, Y -250–50, Z 350–400 mm) is a
  placeholder and does NOT match the real working area (stations sit at
  Z 41–84; robot parks near Z 125–145). Confirm bounds with the operator
  and use `set_workspace_envelope` before real work.
- Job completion reply `{index:1, value:1}` = success; `value:-1` = the
  controller program rejected the job (wrong pattern, or host-point program
  not published). No motion happens on -1.

## Controller-side contract (what the Lua actually runs)

The controller runs the project from `main_hostpoint.bin` — the customer's
`main.bin` (station jobs) plus our `mod_HostPoint` extension. Jobs are
triggered by writing integer system variables in ONE frame:
`0=DeviceID, 1–3=pos selectors, 4=MoveType, 5=ObjType, 6=ClampMode`.
The Lua loop polls every 100 ms, runs the matching module, resets vars,
and replies via SysOutVar.

Host-point extension (device 21): float params `0=X 1=Y 2=Z 3=Rz 4=speed
5=blend 6=E1` (mm/deg), MoveType `1=MoveL 2=MoveJ 3=gripper 4=MoveAbsJ`.
The MCP motion tools wrap all of this — only use `run_lua_job` for patterns
these tools don't cover.

## Known controller quirks (all handled by the server, listed for awareness)

- Pose query (`getFrameWithU0T0`) returns **meters**; commands are mm.
- `getSysParaF/I` return values as **strings**.
- `setSysParaF` only accepts indexes **0–18** (docs claim 0–49; reads work
  to 39).
- After publishing a program via Bioyond Works, the controller resets to
  manual/disabled/stopped, and a paused program that is *resumed* keeps
  running the OLD code — always stop→start after a publish.
- Publishing = TWO steps in Bioyond Works: Import bin into Offline Project,
  then **Publish Offline Project to Controller**.
- One observed unexplained TCP drop mid-command: after any drop, reconnect,
  verify pose/joints unchanged, and clear stale SysVarI (write zeros).

## Autonomous grabbing

The validated grab pipeline (cam1/cam2 rough find → eye-cam calibrated X/Y/Z
→ torque-guided soft descent → grip/lift) is documented as the
**`grab-object` skill** (`.claude/skills/grab-object/SKILL.md`) with its
helper scripts in `grab_skill/` (SDK-exact vision teach port `mcp_teach.py`
— run `py mcp_teach.py test` first, must print ALL PASS — plus pose math,
detectors, and the torque-probe baseline tool). Per-joint torque telemetry
(J1-J4 → SysVarI 13-16) requires `main_hostpoint_trq.bin` published on the
controller. Read the skill before any grab task.

For ArUco-marker-tagged objects at ARBITRARY positions (no taught poses),
use the **`aruco-grab` skill** (`.claude/skills/aruco-grab/SKILL.md`):
anchor-free solve via the fitted eye-camera model + the measured 184 mm
claw lever arm (`grab_skill/aruco_world.py`, constants in
`grab_skill/calibration.json`). Key hazards it encodes: claw ≠ TCP,
center-the-marker-in-view before trusting a solve, J4 winding planned to
the END pose, J2 inner-reach limit. Validated live 2026-07-24 on three
blind placements.

## Handover documentation

- **`HANDOVER_MCP_SKILLS.md`** — robot layer, measured kinematics, safety
  doctrine, calibration architecture (stamps/anchors/self-heal), skills &
  scripts, the standalone grabber, hard-won lessons, physical state.
- **`HANDOVER_OPERATOR_UI.md`** — the Flask console: architecture,
  sequences, UI tour, workflow engine, config files, operating recipes,
  test suite. Read both before continuing the project.

## Files

- `bioyond-s4-mcp/` — MCP server (`server.py`), hardened TCP client
  (`robot.py`), offline test suite (`tests/`, run `py tests/test_offline.py`
  — simulates the controller locally, no robot needed).
- `.mcp.json` — server registration + env config (IP, speed caps, envelope).
- `main.bin` — customer's original controller program (do not delete).
- `main_hostpoint.bin` — currently published program (original + host-point).
- `Bioyond_S4_Agent_Context_Pack/` — protocol spec, manuals, original Lua
  sources, background. Read `01_Project_Context/AGENT_CONTEXT.md` for the
  project's goals and safety doctrine.

## Roadmap

Next phase: integrate the camera feed (Arducam) so agents can locate
objects visually and run autonomous pick tasks — vision will provide
presence/pose of objects, and picks will go through the same envelope-checked
motion tools and taught jobs above. The camera SKU/driver documentation is
not yet in the workspace (see context pack `08_Arducam_Model_Documentation/`).
