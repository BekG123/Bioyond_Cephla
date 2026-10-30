---
name: grab-object
description: Autonomous vision + torque-guided object grab with the Bioyond S4 arm. Use when the user asks to grab/pick/fetch an object in the robot cell. Locates the object with the two context cameras, positions the eye-in-hand camera over it, estimates X/Y/Z from calibrated vision, then descends with per-joint torque monitoring and soft-grabs.
---

# Autonomous grab with the Bioyond S4 (cam1/cam2 → eye cam → torque-guided grab)

This skill encodes the full validated pipeline for grabbing objects with the S4
arm through the `bioyond-s4` MCP server. It was developed and proven on the
Bioyond calibration board (2026-07-20/21) and generalizes to other objects.
Everything is measured/calibrated at runtime — no hardcoded poses.

Helper scripts live in `grab_skill/` at the workspace root:
- `mcp_teach.py` — exact port of Bioyond's Vision SDK teach (detect → select
  trigger config → calibrated image→robot transform → convergence offsets →
  grasp pose). `py mcp_teach.py test` validates it against SDK log ground
  truth (must print ALL PASS). `py mcp_teach.py solve IMG X Y Z RZ` runs one
  teach iteration. Calibration is loaded from
  `Vision_context\S4-VisionDemo\USVisionDemo\VisionServer\Locator\Config\`.
- `sdk_pose.py` — pose compose/invert (SDK Euler convention Rz·Ry·Rx, mm/deg).
- `sdk_detect.py` — the SDK's exact HoughCircles detector + radius→Z offset.
- `circles.py` — general circle-pair detector (Otsu/contours; more permissive
  than the SDK's, useful for first sighting).
- `torque_probe.py` — baseline/band computation for contact detection.

## Non-negotiable safety rules

1. A human must be present at the E-stop for ANY motion. Never clear errors or
   enable without explicit fresh human confirmation (`operator_confirmed=true`
   is passed only after the human says so — each time, not once per session).
2. TCP drops happen before/around most commands. On "not connected" → connect
   and resend. On "connection lost while the command was executing" → the
   physical state is UNKNOWN: re-query `get_status` + `get_cartesian_pose`
   before ANY retry. Never resend a motion blind.
3. Small steps, low speeds (≤30 travel, ≤15 approach, ≤8 near objects, 5 when
   probing). Keep reach radius sqrt(X²+Y²) < 480 mm (fault 3570 beyond).
4. Torque-probe stop rule (learned the hard way): the noise band is a
   TRIPWIRE, not a debate. On FIRST breach of any joint's band: STOP
   descending. To discriminate drift vs contact, RETREAT 0.5-1 mm and
   re-read — drift follows the trend back, contact unloads sharply. Never
   press deeper to "confirm".
5. Grip only at proper engagement depth. Closing the gripper high on an
   object's top edge jams the plates and trips J4 collision. If descent is
   blocked before grip depth, the placement or approach is wrong — reseat the
   object or approach from another side; do not close anyway.
6. After any collision trip (error 3873, servos drop): first verify clearance
   for BOTH jaw opening and the upward retreat. Near a rack, a free claw and
   clear upward path do not imply that spreading the jaws is clear (rack
   recovery fault, 2026-10-09). If either is unknown, keep disabled/stopped
   for physical inspection; do not automatically open or restart (restart
   closes E1). Once both are established: report to the user,
   wait for their all-clear, then clear errors, enable, OPEN THE GRIPPER
   FIRST (releases jams without arm motion), and retreat straight UP.

## Session bring-up

1. `connect` → expect auto + enabled + program running + lua_app_initialized.
   If the program is paused: `stop_program` then `start_program` (a resume
   runs stale code). If disabled/manual: ask the human, then `switch_mode`,
   `enable_robot(operator_confirmed=true)`, `start_program`.
   NOTE: program start resets E1 to 0 (closed). Never start the program while
   an object is held.
2. `set_workspace_envelope` for the task area (operator confirmed). Working
   values used for the balance/nest area: X 180-470, Y -400..-100, Z 35-420.
3. Verify the torque report: trigger `gripper_status`, then
   `read_system_values(var_i_indexes=[13,14,15,16])` — nonzero J1 confirms
   the extended program (controller/main_hostpoint_trq.bin) is live. If 13-16 read zero,
   the extended program is not published — torque-guarded descent is
   unavailable; stop and tell the user.

## Hardware facts (verified live)

- Pose queries return mm via `pose_mm` / degrees via `rotation_deg` — only
  ever feed those back into moves.
- E1 gripper: 28 fully open; value ≈ plate gap minus ~60 mm finger offset.
  Calibration board: open 18, closed-on-board 2. Well plate: stalls at 23.34,
  grab at 23.0 or use `grip_by_torque`. Free torque +150..+195; gripping =
  torque < −100 AND position stall > 0.15.
- Torque report (after triggering the report job via `gripper_status`):
  SysVarI 10-12 = E1 pos/torque/normtorque ×1000; SysVarI 13-16 = J1-J4
  normalized torque ×1000. J1 (Z axis) idles at ~350-520 counts (gravity
  holding) and DRIFTS ~2-5 counts per mm of Z travel — judge it against a
  local trend. J2-J4 idle near 0 (±15). Noise band ≈ ±25 counts.
  Contact signature: J1 drops (structure takes arm weight); J3/J4 move on
  lateral/twist contact.
- Eye-in-hand GigE camera (3072×2048 mono): ~13-15 px/mm at working depths.
  If a capture times out or frames are black: `gige_release` then recapture.
  If frames are dark (mean < 128), the detection scripts auto-normalize
  brightness — but flag it to the user (lighting/exposure changed).
- The two Arducams can swap enumeration after reboots — verify by scene:
  cam1 = frontal view (balance left, robot center), cam2 = along-bench view.
- One camera controller at a time: kill `VCS.Test` before MCP gige capture;
  release gige before running any Bioyond vision software.

## Phase 1 — rough localization (cam1 + cam2) — MANDATORY FIRST, NO RASTER

Never free-scan the workspace with the eye-in-hand camera — that wastes arm
motion and time. The fixed context cameras ALWAYS come first; the eye cam is
only sent to candidate locations they produce.

1. `camera_capture` (cam1, frontal) and `camera2_capture` (cam2) with grid.
   READ the images yourself; find the target object the user described.
   Zoom with `camera_inspect_region` / `camera2_inspect_region` on EVERY
   plausible blob until you have explicit candidate locations (or have
   positively ruled a region out) — be thorough here, a few extra zooms are
   far cheaper than eye-cam search moves.
2. Produce a short ranked list of candidate world locations from the pixel
   evidence. Only then move the eye cam to candidate #1, verify (circles.py
   or your own reading), and proceed; if wrong, candidate #2. If the fixed
   cameras genuinely cannot see the object anywhere (fully occluded), say so
   and ask the user rather than blind-scanning.
2. Map pixels → rough robot XY using the known scene anchors (balance nest at
   ~X 217-290, Y -344..-320; deck stations at Z 41-84) and cam1 scales
   (Y ≈ horizontal ~2-3.8 px/mm, Z ≈ vertical ~2.3 px/mm at bench depth).
   Accuracy needed here is only ±30 mm — enough to place the eye cam over it.
3. Plan an obstacle-free approach from the images (fluidics rack, nest walls,
   tubing). Travel at Z ≥ 250 in the nest area.

## Phase 2 — eye-cam positioning + X/Y/Z estimation

Move the eye camera over the rough location at Z ~265-270 (≈200-235 mm above
deck objects; the calibrated vision works at camera-to-object ~205-240 mm).

For the CALIBRATION BOARD (or any taught object) — use the SDK-exact teach:
1. Capture: `gige_capture(grid=false)`.
2. `py grab_skill\mcp_teach.py solve IMG X Y Z RZ` (current pose in mm/deg).
3. It returns: detection, selected trigger config, `move_xyrz` / `move_z`
   corrections and errors. Apply the correction with `move_to_cartesian`
   (joint interp for large Rz changes, linear otherwise), recapture, repeat
   until `xy_err_mm` < 0.3, `rz_err_deg` < 0.2, `z_err_mm` < 0.3 (detection
   noise floor; typically 3-6 iterations). Retry a failed detection up to 3×
   (transient Hough misses are normal).
4. The converged solve's `grasp_if_converged` = the grasp pose (X, Y, Z, Rz).
   Sanity-check it: reach < 480, Z plausible for the station (nest grips
   land at Z ~41-53), Rz reachable.

For UNTAUGHT objects — same structure, generic measurement:
1. Detect/locate the object in the eye image yourself (or with `circles.py`
   for circular features).
2. Measure the local Jacobian live: two small known moves (±6-8 mm X, then
   Y), track the feature shift → 2×2 px/mm matrix (should be ~orthogonal,
   equal magnitudes — if not, re-measure). Solve the XY correction to center
   the feature; iterate once or twice.
3. Estimate height from scale: capture at two Z (10-12 mm apart), feature
   size ratio → distance (r ∝ 1/H). Grasp Z = measured object top − grip
   engagement depth for that object. When in doubt, let the torque probe
   find the top instead of trusting a single estimate.
4. Compute grasp XY from the camera→grip offset: at Rz 0 the grip point is
   ≈ (X +7.2, Y −10.8) mm from the camera axis (flips sign with tool
   rotation) — or anchor on a previously successful grasp of the same object.

Wrist management: rotate Rz to the grasp orientation in ≤30° steps at safe
height BEFORE descending (J4 then moves the short way; a single large
end-of-path rotation can wrap ~360°).

Motion interpolation rule (learned from an axis-3 collision): `joint`
interpolation follows an unpredictable Cartesian arc — the tool can swing far
off the straight line (even past the robot column). Use `joint` ONLY for
pure in-place Rz rotations (same XYZ). ALL translations use `linear`. Never
combine a large rotation with a translation in one joint move, especially
near tall stations (Squid tower, fluidics rack, column).

Claw opening depends on the grip approach (set BEFORE descending):
- Wide config (straddles the board's SHORT span): open E1 = 18.
- Long config (straddles the board's LONG span): open E1 = 28 (fully open —
  the long span barely fits inside the fully-open plates).
- Generally: opening must exceed the straddled dimension of the object; when
  in doubt open fully (28) and let grip_by_torque close from there.

## Phase 3 — torque-guided descent (soft approach)

1. Descend normally (speed 15-20) to grasp_Z + 20 mm.
2. Baseline: trigger `gripper_status` + read SysVarI 13-16, 4-5 times
   stationary. `py grab_skill\torque_probe.py baseline "j1,j2,j3,j4" ...`
   → per-joint mean and band (3σ, floor ±25).
3. Step down 1 mm (0.5 mm within 6 mm of expected contact/grip depth) at
   speed 5. After EVERY step: trigger report, read 13-16, compare.
   - J1: compare against the local trend (last 2-3 readings), not the
     static baseline — it drifts with Z.
   - J2-J4: compare against the static baseline band.
4. FIRST breach of any band → STOP (rule 4 above). Retreat 0.5-1 mm,
   re-read: contact confirmed if the deviation unloads on retreat.
5. On confirmed contact BEFORE reaching grip depth: capture cam1/cam2 +
   inspect — identify what was touched (nest rim, neighbor object, the
   object's edge). Re-plan: shift XY away from the obstruction, approach
   from another side, or ask the user to reseat the object. NEVER close the
   gripper at a blocked depth.
6. If grasp Z is reached with no breach: proceed to grip.

## Z-touch calibration (persistent, refreshable)

`grab_skill/calibration.json` stores `z_touch_offset_mm` = (torque-probed
contact Z) − (vision grasp Z): the gap between the SDK's taught full-straddle
depth and the physically reachable depth on the current support surface
(measured ≈ +9 on both nest and deck). `safety_margin_mm` (5) keeps the plate
tips clear of the surface — no bottoming, no scratching.

- USE: descend to `grasp_z_calibrated` from the solve output
  (= vision Z + offset + margin) with the torque guard still armed as a
  backstop, then grip there with `grip_by_torque`. Do not descend to the raw
  vision Z.
- REFRESH (user says e.g. "I placed the board on X, calibrate"): run the
  vision teach to convergence, note the vision grasp Z, then torque-probe the
  descent to first CONFIRMED contact (stop → retreat → re-descend compare).
  New offset = contact Z − vision Z. Update calibration.json (append to
  history, set z_touch_offset_mm), lift back to safe height. No grip needed.
- The margin trades engagement depth for surface safety: gripping higher
  holds less of the object's edge. If `grip_by_torque` reports no grip at the
  calibrated Z, reduce the margin in 1-2 mm steps (still above contact) and
  retry rather than plunging to contact.

## Phase 4 — grip, verify, lift

1. Close the gripper slowly: `move_gripper(closed_value, speed=10)` (board:
   2; unknown objects: `grip_by_torque` instead — it finds the stall itself).
   If the close command's connection drops mid-execution: re-query state,
   then `gripper_status` to see whether the close actually happened before
   re-issuing.
2. Verify grip: E1 torque < −100 and position stalled above the command
   (board grips report saturation ≈ −187). Free/empty ≈ +150..+195 = MISSED:
   reopen, lift 20 mm, re-run Phase 2.
3. Lift straight up (speed 8-10) to Z ≥ 150. Re-read torque: still negative =
   object held.
4. Visual confirmation: cam1 capture — object gone from its resting place
   and/or visible in the jaws. Report the result honestly.

## Known failure modes

- "not connected" before a command: benign; reconnect, resend.
- Drop DURING a command: state unknown — re-query pose/status first.
- Collision 3873: servos drop, program pauses. Human all-clear → clear
  errors → enable → gripper open → retreat UP. Axis 1 = Z ram; axis 4 =
  wrist twist (usually a jammed close).
- MoveJ "unable to retrieve target joint" (3882): target unreachable by
  joint interp — use linear, or an intermediate pose.
- Vision teach converges but grasp collides: the object moved/reseated since
  the calibration anchor, or its placement blocks the approach (e.g. board
  < 6 mm from the nest rim). The vision measures the OBJECT, not clearances
  — the torque probe is the clearance check.
- Bioyond's own VisionTeach demo (RobotSDK port 52525) silently no-ops all
  moves while the MCP Lua program is RUNNING — stop the Lua program before
  running their software; conversely MCP motion NEEDS the program running.

## Publishing note

Torque slots 13-16 exist only in `controller/main_hostpoint_trq.bin` (repo controller package).
If the controller program is ever re-published from another bin, torque
probing dies (13-16 read 0) — re-publish the trq bin via Bioyond Works
(Import into Offline Project → Publish → back to auto+enabled).
