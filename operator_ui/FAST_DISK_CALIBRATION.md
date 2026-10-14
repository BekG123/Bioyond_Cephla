# Fast two-circle disk calibration

Implemented in `Pick and Hold/Calibration/fast_disk.py` (repository root), with
`operator_ui/fast_disk.py` retained as a compatibility import. Called by
`sequences.seq_find_disk`. The Flask
button is **Fast calibrate disk**. This estimates a grasp target; it does not
re-fit the camera model, align, descend to grasp depth, grip, or search.

## Reading the implementation (consolidated 2026-09-21)

Read `Pick and Hold/Calibration/fast_disk.py` from `start_calibration()`.
The main loop, step planning, readiness/pose conversion, IK/path/arrival guards,
disk detection, vendor pose math, annotation and offline selftest now live in
that one file. Numbered sections follow the main flow. Camera SDK and locked
robot transport remain shared drivers. Flask/Runner only dispatch and report.
`teach.py`, `mcp_teach.py`, `sdk_pose.py` and the shared helpers imported through
`autonomy.py` delegate to this implementation. The historical vendor CLI retains
its original output contract. Existing JSON calibration data stays in place.

Fast speed 10 and convergence settings are preserved. OriginalDiskGuard keeps
its own speed-5 wrist cap, independent of Fast's speed setting. This source
reorganization does not reload a running Flask process or command the arm.

## Algorithm

Continuous visual feedback with bounded steps using the existing SDK-exact teach math, not A*.
There is no commissioned collision occupancy map for A* to search. Joint-path
and TCP-envelope checks are not mesh collision checking; the operator must
verify the arm, camera and gripper's whole swept volume, including the rack.

1. Clear the old target, check controller/envelope/joints and vendor selftest.
2. Capture a fresh frame; detect the circle pair once and evaluate both vendor
   configurations from that same detection. Pin the lowest-cost valid camera
   route. Cost ranks translation distance plus yaw change, not predicted seconds.
3. Preflight the complete camera correction on the current J2/J3 branch. Keep
   J2 within +/-93 degrees and existing J4/singularity margins. Reject the
   exact camera constraint with a diagnostic; never expand the envelope.
4. Version 3 centers XY/height before small yaw corrections (<=2 degrees).
   While fixed-wrist center error or height error is >=1 mm, use the vendor's
   `move_center` translation plus `move_z` height correction, holding wrist yaw.
   Do not chase `move_xyrz`'s XY while skipping its assumed rotation. These are
   scheduling thresholds, not relaxed final convergence tolerances.
   Before ANY yaw correction, require three fresh stationary images whose
   signed yaw errors all exceed 0.2 degrees in the same direction, with total
   spread <=0.2 degrees. Correct the median signed yaw. Disagreement causes
   stationary recapture, not a lift/rotation. Pose changes invalidate review.
   Large yaw (>2 degrees) may still be corrected before centering, but also
   requires this stationary confirmation. Version 4 keeps recapturing during
   inconsistent stationary yaw until it becomes usable, the operator stops,
   or a detection/telemetry fault occurs. It does not move on noisy yaw alone.
5. If a confirmed yaw correction is needed, lift to TCP Z >=300, rotate in place in <=10
   degree segments using the service's dedicated **joint-interpolated pure
   wrist** command (XYZ pinned live). `DiskGuard` checks the path, joint limits,
   clearance height and segment size before the command, and verifies pose AND
   joint arrival afterwards. Recovered/uncertain feedback stops without retry.
   Go to the higher of starting and corrected observation height, then obtain
   a new image. This avoids returning down to the old height only to rise again;
   going below the starting observation height still needs fresh feedback.
   Translation segments remain <=10 mm XY / 5 mm Z, speed 10, linear interpolation.
   This orientation phase follows a fully prechecked route with live checks
   per segment; there is no blind translation to chase a lost circle pair.
6. Otherwise combine bounded XY and Z correction with fixed wrist yaw, then
   capture again. The full vendor target includes the small Z component of
   `move_xyrz` as well as `move_z`. No extra final up/down Z sampling excursion.
7. Require two consecutive fresh stationary images, each within the existing
   vendor tolerances (XY <0.3 mm, yaw <0.2 degrees, Z <0.3 mm). Their grasp
   estimates must agree within 1 mm XY/Z and 0.5 degrees yaw. Average these
   two estimates; publish calibrated Z with the existing touch offset.

Camera-to-disk working distance is not TCP Z. The vendor configs teach an
optical distance of 205 mm and use circle radius to calculate the TCP height
correction; no hard-coded TCP Z of 205-250 is substituted.

The future grasp may lie outside the current camera-motion box. That produces
a separate warning, not a calibration failure. The published target explicitly
requires alignment preflight. Align/Descend retain their existing complete-path,
envelope, joint, clearance and torque checks. Calibration success does not
prove that a collision-free grasp path exists.

## Stops and bounds

Version 4 has no fixed observation count, elapsed-time limit, accumulated-travel
limit, or orientation-phase count. It continues until two agreeing converged
images, operator cancellation, or a fault. Repeated improving yaw corrections
are allowed. Three confirmed yaw corrections with two successive increases
greater than 0.2 degrees abort; the existing positional divergence check remains.
History buffers retain only the three observations needed for these checks.
Detection retries are stationary (three fresh frames), never a search. Lost
detection, increasing errors, disagreement, stale arrival, recovered connection,
invalid/no-motion solves or missing telemetry stop without a target. Stable
but non-converging residuals can continue indefinitely and require operator Stop;
this does not guarantee that inaccurate calibration or noise will converge.
No failed motion is retried. This is NOT a real-time emergency-stop mechanism.
The UI STOP button stops between segments; hardware E-stop is immediate.

First motion requires live joint/gripper telemetry with no holding-torque
evidence. This does not prove empty jaws; the operator must confirm that too.

## Deployment and test

The running Flask process does not hot-reload Python. Version 1 was tested live
and exhausted its 120-second budget: the pure-yaw MoveL took about 70 seconds.
Version 2 replaces that command with checked pure-yaw MoveJ and removes the
height detour. In the next live run, the two small MoveJ commands each took
about 0.8 seconds, but single-frame yaw threshold crossings caused repeated
lift cycles and an abort. Version 3 adds translation-first scheduling and
stationary yaw confirmation. Version 4 removes fixed run budgets and reports
views, residuals, moves, elapsed time and total travel during convergence.
Version 4 passed the recorded speed-5 and speed-10 live runs on 2026-09-19;
see `Pick and Hold/Calibration/Observations.md`. The consolidated source passed
137 offline tests, 12 unchanged recorded solves, and the 2026-09-21 live test:
Wide at speed 10 converged in 66.563 seconds / 46 views / 35 moves, including
a ~23.8-degree wrist correction. Final XY/Z/yaw residuals were
0.219 mm / 0.242 mm / 0.109 degrees. The startup torque-report timeout still
occurred; status/pose and two subsequent live reports were checked before motion.
Full log: `operator_ui/reports/live_fast_calibration_refactor_20260921_005213.json`.
Restart the
console only while the robot is idle and
in a safe operator-controlled state; do not restart the robot Lua program.
Reload the browser. The new UI uses `/seq/find_disk_fast` so an old backend
returns 404 rather than silently executing the old Find algorithm.

After restart, `/seq/find_disk_fast` invokes this sequence. `/seq/find_disk`
and `/seq/find_disk_original` invoke the separately restored original routine;
their limits and fallback behavior are unchanged. Both variants require JSON
booleans `confirm`, `cell_clear`, `empty_gripper`
all true, supplied by the GUI only after its confirmation dialog is accepted.
Do not set these flags without fresh operator confirmation. No enabling or
error clearing is performed by this sequence.

Offline tests (no live robot connection):

```
py -m unittest discover -s operator_ui/tests -p test_fast_disk.py -v
py -m unittest discover -s operator_ui/tests -p test_alignment.py -v
py -m unittest discover -s operator_ui/tests -p test_transfer.py -v
py -m unittest discover -s operator_ui/tests -p test_pickup.py -v
```

The deterministic fake-vision 20 mm XY / 10 mm Z case takes two combined moves
and four detections including the stationary confirmation. This measures loop
behavior, not physical calibration speed or vision accuracy. Live time must be
measured in a supervised trial. Log/result include views, moves, elapsed time
and travel distance; v2 also logs each segment's measured elapsed time. A fake
latency regression exercises the corrected height and dispatch choice, but its
assumed MoveJ timing is NOT a hardware speed measurement. The legacy full
offline harness has known inconsistent
fake pose/joint/torque fixtures; it is not claimed to pass these newer guards.

`seq_find_disk_legacy` is retained only as historical source, with no Flask route.
Generate Anchor and ArUco calibration have not been changed by this feature.
