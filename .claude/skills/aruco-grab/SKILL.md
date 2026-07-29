---
name: aruco-grab
description: Anchor-free grab of an ArUco-marked object with the Bioyond S4 at ANY deck position. Use when the user asks to grab/pick an object tagged with an ArUco marker. Solves the marker's world pose through the fitted eye-camera model, compensates the 184 mm claw lever arm, plans a J4-safe approach, and grabs with torque-guarded descent + torque-stalled close. Validated live 2026-07-24 at three blind positions.
---

# ArUco grab (fitted camera model + claw-arm compensation)

Grabs a marker-tagged object at an arbitrary position — no taught poses, no
convergence servoing. Everything flows from measured constants in
`grab_skill/calibration.json` and one capture with the marker near image
center. Proven on three operator-blind placements (final grips: torque
saturation −187, verified by lift).

Helper scripts (workspace root `grab_skill/`):
- `aruco_world.py solve IMG X Y Z RZ [size_mm]` — THE solver: marker world
  XY/Z + yaw, plus claw-arm-compensated grab candidates (TCP + wrist Rz,
  reach/feasibility) and grip_z. Constants auto-loaded from calibration.json.
- `aruco_detect.py detect IMG [size_mm]` — raw detection (corners, PnP,
  side_px) when you need just the measurement.
- `fit_eye_cam.py` — the least-squares mount fit (edit the D table with
  fresh capture rows). Re-run whenever the camera/bracket is touched or
  solves are needed at wrist angles far outside the fitted range.

All safety rules of the `grab-object` skill apply verbatim (human at E-stop,
operator_confirmed only after fresh human say-so, small steps, reconnect-on-
drop / re-query-on-mid-command-drop, first-torque-breach-stops, no closing at
blocked depth). Bring-up is identical (auto + enabled + program running via
stop→start, torque slots 13-16 nonzero, envelope set for the task area).

## The model (why this works with zero anchors)

- The eye camera rides the WRIST on a lever arm; the CLAW rides a second,
  much longer arm. Neither is at the TCP:
  `marker_world = TCP + R(Rz)@cam_arm + R(Rz + yaw_off)@diag(1, mirror)@pnp_u`
  `claw_world   = TCP + R(Rz)@claw_arm`        (claw_arm ≈ (183.7, −3.9), 184 mm!)
- Grab: `TCP = grab_point − R(Rz_grab)@claw_arm`,
  `Rz_grab = disk_axis + WRIST_REL (±180)` where `disk_axis = marker_yaw
  + rel_yaw` from the id's disk calibration (marker PRINT orientation
  cancels; marker yaw alone is only the fallback for uncalibrated ids).
  WRIST_REL is a PURE claw constant ≈ 90° − claw-arm angle — it makes the
  two opposite approach TCPs exactly perpendicular to the plate edge
  (checked live to 0.01°; a 2° error here shows as ONE finger rubbing its
  near edge identically at both wrist sides).
- The vendor's taught triggers hide the claw arm by demonstration; absolute
  grabs MUST subtract it explicitly. Assuming claw=TCP misses by ~184 mm.
- Constants provenance: camera fit = 6-view least squares (translations +
  ±15° rotations, RMS 2.35 mm, mount-frame model selection); claw arm = two
  independent anchor-free derivations off the vendor demo (0.4 mm agreement).

## Procedure

1. **Capture + solve.** `gige_capture(grid=false)` (grid breaks detection),
   then `py grab_skill/aruco_world.py solve IMG X Y Z RZ` with the exact
   `pose_mm`/`rotation_deg` values. Marker size auto (16.553 mm — the
   "20 mm" sheet printed at ~83 %); if a NEW marker sheet is used, verify
   scale with the two-height check (capture at ΔZ = 30 mm;
   `H = ΔZ·s2/(s2−s1)`; size_true = size_assumed·H_geo/H_pnp).
2. **CENTER-VIEW RULE (mandatory before trusting numbers).** The camera fit
   was trained at Rz 64–94°; a solve from Rz 137° carried a +12 mm Y bias.
   If the marker is far off image center OR the wrist far outside 64–94°:
   move so the marker sits near the image CENTER (pnp u → 0 kills the
   yaw/mirror terms; a centered solve is trusted at any wrist angle), then
   re-solve. Two consistent center-ish solves ⇒ proceed.
3. **Pick the grab candidate.** The solver emits ALL FOUR approaches —
   two clamp axes (width / length, from the id's disk calibration) × two
   wrist sides — each with its span and a `clampable` flag against the
   claw window (max gap 88 mm at E1 28, min 60 at E1 0). The span is
   INFORMATIONAL only — the operator removed the hard claw-window gate
   (2026-07-28: "I will take care of that"); the UI warns loudly when
   the picked way's span falls outside the window, and the descent
   guard remains the physical protection. Feasibility is
   EXACT now (kinematics fitted 2026-07-28 with 0.00 mm residual on 8
   live poses, stored in robot_params.json): the arm is a planar 2-link
   with its J2 axis at world **base (126, 0)** and **L1 = L2 = 200** —
   `P = base + L1·e^{i·J2} + L2·e^{i(J2+J3+180°)}`. Reject a candidate
   when (a) extension `|TCP − base| > 400 − 15` margin (the 3570 fault
   target was 3.6 mm past true full stretch — J4 can't track the wrist
   near extension; note the limit circle is around the BASE, not the
   world origin), (b) predicted **J2 < −95° + 2°** via the exact IK (a
   3571 fault froze J2 at −95.10 live; the IK reproduces that stop to the
   decimal), or (c) outside the envelope. The old flat radius guards
   (480/280) were pre-fit approximations. If NOTHING is feasible, compute
   all four sides, show the table, and ask the operator to rotate or move
   the object — do not force it. NOTE the claw-overhang trick
   (operator-taught): the claw extends ~191 mm beyond the TCP, so objects
   sitting far beyond TCP reach (validated live at reach 536) ARE
   grabbable from their near side — the far-side twin is then
   unreachable, single-candidate territory.
4. **J4-safe wrist plan (compute BEFORE moving).** In-place rotation moves
   J4 by exactly the commanded delta; translation then shifts J4 by
   −Δ(J2+J3). Read joints, estimate J4 at the END pose
   (`J4_end = Rz_grab − (J2+J3)_target`; (J2+J3) ≈ −141° near reach 300),
   and pick the winding (short way or ±360) that keeps the WHOLE path
   inside ±205 hard / prefer ±150. Rotate in-place in ≤90° chunks at
   Z ≥ 300 — the claw sweeps a 184 mm arc, keep it above everything.
5. **Approach.** Translate at Z ≥ 300 (capped steps), hover over the grab
   TCP, open claw to 28 (or narrower ONLY if the operator flags an adjacent
   obstacle), descend fast (15) to `grip_z + 20` (grip_z = marker_z + 9,
   the z-touch offset — no safety margin, operator's standing order).
6. **Torque-guarded descent** to grip_z: 5-read stationary baseline; steps
   1 mm (0.5 mm in the last 6 mm) at speed 5; after EVERY step read SysVarI
   13–16. J1 vs the post-step trend ONLY (never the stationary baseline —
   direction artifact; first post-step read seeds the trend; slow dips that
   REPRODUCE on re-descend are positional, not contact). J2–J4 vs baseline
   ±25 (baseline in the working pose — idles are configuration-dependent).
   First breach → stop, retreat 1 mm, discriminate; never press to confirm.
7. **Grip.** `grip_by_torque(start=28, torque_threshold=-100, floor=0.5,
   step=0.1, coarse_step=0.5, fine_from=6)`. Success = torque < −100 with
   position stall (saturation ≈ −187). The stall E1 + 60 = the object's
   clamped span — compare with expectation; a surprise span means you
   gripped a different object/orientation than assumed.
   If it reports no grip: do NOT retry blind — the usual causes are (a) the
   object is narrower than the floor allowed (lower the floor), or (b) too
   shallow an engagement (descend 2 mm, retry once), else re-check vision.
8. **Lift + verify.** Straight up at speed 8–10 to Z ≥ 120; re-read
   gripper: torque still strongly negative = held. Report honestly.

## Known traps (each cost real debugging)

- **Claw ≠ TCP** (~191 mm arm) — the founding bug of this skill.
- **STALE CONSTANTS AFTER A CAMERA REFIT** — the claw arm and wrist_rel
  are extracted THROUGH the camera model, so they silently absorb its
  bias. Any change to eye_cam_fit (new fit, new u_scale/tilt) invalidates
  them: re-derive both from the stored vendor anchors immediately
  (2026-07-28: a stale arm put one finger over the plate — 7.7 mm clamp-
  axis miss; re-derived under the current model, next blind placement
  held dead-center first try). Stamp derived constants with the model
  version they came from.
- **STALE value-1 ACKS after TCP drops** — after any reconnect, a motion
  can return success while the controller actually faulted mid-path.
  ALWAYS compare pose_after against the commanded target; on mismatch
  re-query status/errors before anything else.
- **Off-range viewing bias** — center the marker in view before trusting.
- **J4 soft limit ±220** hit twice live (3571): once rotating short-way,
  once because the TRANSLATION wound it further. Plan end-state J4.
- **J2 soft limit −95°** blocks close-to-column approaches (3571 mid-path,
  arm freezes at the limit); the outer limit is the extension circle
  |P − base| = 400 around the base (126, 0), NOT an origin circle (3570
  near it). Predict J2/J3 with the exact IK from robot_params.json
  (base + links) instead of any flat radius guard — sequences._ik_j2j3 /
  _reach_block implement it, aruco_world's feasible flag uses it too.
- **Marker print scale** — never trust the nominal size; two-height check.
- **Two markers / reflections in glossy lids** — sanity-check the candidate
  location against where the operator says the object is; if two sightings
  disagree by ~190 mm, one of them is not your object.
- **Envelope**: pure in-place rotations are refused too if the TCP is
  parked outside the box — widen (operator-confirmed) before recovering.
- **E1 zeroes on program start** — never stop/start while holding.

## Per-ID disk calibration (marker -> true disk center)

The marker is rarely glued at the exact grab point. One-time fix per id:
place the tagged disk on a plain CONTRASTING background and run
`aruco_world.calibrate_disk(img, X, Y, Z, RZ)` (UI: "1c Calibrate disk
ID") — it edge-detects the disk outline (Otsu both polarities, contour
containing the marker, min-area rect), measures the marker->disk-center
offset in the MARKER frame plus relative yaw and true spans, and
`save_disk_cal()` stores it under `calibration.json -> marker_offsets[id]`.
Every later `solve()` applies the offset automatically at any object
rotation and any background — one image is then enough. ALWAYS eyeball the
annotated rectangle before trusting a fresh calibration, and check the
spans against the claw's clampable window (60–88 mm gap).

Two hard-won rules about these entries (2026-07-28, ring tray):
- **The id belongs to the OBJECT, not the sticker.** A marker recycled
  onto a different object silently carries the old spans/offsets — the
  descent guard caught a 13 mm depth error that way. Recalibrate whenever
  the marker is re-glued.
- **`grip_z_offset_mm` (optional per-id field)** overrides the global
  z-touch when the marker sits RECESSED below the grip plane (e.g. lying
  on a tray's contents): grip_z = marker_z + this. Measure it from the
  torque guard's contact stop (contact TCP − marker_z), then verify by a
  grip whose stall span matches the stored width.

## Standalone program

`grab_skill/grab_aruco.py` is the whole pipeline as one CLI (no browser,
no MCP): bring-up guards -> find (center-view, 2-agree, multi-viewpoint,
XY mean + Z MEDIAN) -> exact-IK candidate pick -> J4-planned align ->
optional `--hold` verdict stop at grip+20 -> torque-guarded descent ->
torque-stalled grip with span sanity -> slow lift + held check. It reuses
the console's tested layers (robot_service with arrival-verified moves,
camera_service, sequences) and REFUSES to run when calibration.json's
model-version stamps say the claw arm predates the camera fit. Its module
docstring is the distilled algorithm log — every rule with the live
failure that taught it.

## Porting to a NEW arm (nothing is hardcoded)

Every arm-specific value lives in two config files; the calibration flows
measure them — code never needs editing:
- `grab_skill/calibration.json`: eye_cam_fit (lever arm, yaw, tilt,
  u_scale, mirror — ALL auto-fitted, mirror included), h_scale (marker
  size / Z slope, regressed from the calibration's height rows),
  cam_z_offset_mm, claw_arm_tool_mm, wrist_rel_deg, z_touch_offset,
  marker_offsets per id, model-version stamps (eye_cam_fit.fitted /
  claw_arm_model_version — written by save_mount / save_claw_arm).
- `operator_ui/robot_params.json`: the planar kinematic block (base_x/y,
  link1/link2, j2/j3 offsets, j2_min + margins — fit it from ≥4 logged
  (J2, J3, X, Y) pairs spread across DIFFERENT approach angles with a
  6-param Gauss-Newton incl. the base offset; a narrow-sector fit
  converges to phantom parameters that nail the sector and break
  everywhere else, which happened live), j4 pref/hard limits, claw gap
  min/max, legacy reach_hard_mm/inner_reach_mm fallbacks.

New-arm bring-up order: (1) edit robot_params.json with the arm's limits
(+ fit the kinematic block from logged pose pairs); (2) UI "0 Generate
anchor (vendor)" — converges to the vendor's taught view of the
calibration disk with the vendor's own code/values, then ASKS the
operator "was the run successful?" before persisting the ground-truth
anchor triplet (mark pixel + capture pose + trigger grasp TCP) to
`grab_skill/anchors.json` — a bad convergence must never become truth; (3) UI "1d Calibrate camera" — fits
the whole camera model AND then AUTO-re-derives the claw arm + wrist
relation from the stored anchors (stamps match, grab-ready — this
auto-heal runs after every future refit too); (4) only if no vendor demo
exists: the "Calibrate claw arm" two-press jog flow at two wrist angles
+ "Save wrist relation" instead of (2); (5) z-touch via a torque-probed
descent (Z-cal box); (6) "1c Calibrate disk ID" per object. After that
the full pipeline runs.

## Refitting the camera model

Collect ≥6 rows: vary TCP (±30 mm, 2 axes) AND wrist (±15° or more — wider
is better), marker in frame everywhere; record TCP/Rz/joints (from
`joints_after`), pnp `cam_xyz_mm` and `cam_yaw_deg` (fixed size). Put them
in `fit_eye_cam.py`'s D table, run, take the lowest-RMS model (should be
'tool' frame, mirror −1, RMS < 3 mm) and write the winning constants into
`calibration.json → eye_cam_fit`. THEN re-derive the claw arm + wrist_rel
— on THIS arm run `py grab_skill/rederive_claw_arm.py --save` (re-solves
the stored vendor grab anchors through the new model; refuses to save if
the two anchors disagree > 1 mm); on an arm without anchors use the UI
two-press jog flow at two wrist angles. The model-version stamps
(eye_cam_fit.fitted vs claw_arm_model_version) gate the standalone
grabber and warn in the UI until this is done.
