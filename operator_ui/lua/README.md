# Queued taught replay

## Speed-137 experiment (version 220108)

Prepared package: `main_hostpoint_trajectory_137.bin`. Only the trajectory module
differs from speed 130: version 220108 and a 137 mm/s ceiling. Host permits 137
only for the two `entry_speed137_*` reviewed variants with separate one-run
permissions. Same geometry, acceleration, blending and collision settings.
Publish and freshly verify 220108 before execution. Hardware results belong in
Observations.md; the 10-second objective is not a measured result or guarantee.

## Speed-130 research update (version 220107)

Prepared package: `main_hostpoint_trajectory_130.bin`. Only the trajectory module
differs from the retained speed-100 package: version 220107 and a 130 mm/s ceiling.
Host permits 130 only for the two `entry_speed130_*` reviewed variants, each with
a separate one-run permission. Geometry, acceleration, blending and hardware
collision settings are unchanged. General replay limits retain their prior values.
Publish and freshly verify 220107 before testing. See Observations.md for results;
preparing and testing the package offline does not constitute a hardware run.

## Final speed-100 experiment (version 220106)

Prepared package: `main_hostpoint_trajectory_100.bin`. Relative to speed 80,
only the trajectory Lua module changes: version 220106 and a 100 mm/s ceiling.
Host permits 100 only for `entry_speed100_toward_home` and
`entry_speed100_to_hamilton`, preserving geometry and one-run permissions.
Earlier versions retain their own ceilings; general Cartesian/replay limits,
acceleration, blending and hardware collision settings are unchanged.
Publish and freshly verify 220106 before execution. This is the user's final
speed/time experiment, not an authorization for higher speeds or automatic repeats.

## Speed-80 research update (version 220105)

Prepared package: `main_hostpoint_trajectory_80.bin`. Only the trajectory Lua
module differs from the retained speed-70 package: version 220105 and an 80 mm/s
queue ceiling. Host permits 80 only for `entry_speed80_toward_home` and
`entry_speed80_to_hamilton`; geometry and separate one-run authorization are
preserved. Earlier versions retain their own ceilings. General Cartesian/replay
limits, acceleration, blending and hardware collision settings are unchanged.
Publish and freshly verify 220105 before testing 80. See Observations.md for
hardware status; offline execution tests do not establish hardware performance.

## Speed-70 research update (version 220104)

Prepared package: `main_hostpoint_trajectory_70.bin`. Only the trajectory Lua
module differs from the retained speed-55 package: version 220104 and a 70 mm/s
queue ceiling. Host permits 70 only for `entry_speed70_toward_home` and
`entry_speed70_to_hamilton`, with unchanged refined geometry and separate one-run
permissions. Earlier controller versions remain supported at their own ceilings.
General Cartesian/replay limits, acceleration, blending and hardware collision
settings are unchanged. Publish and freshly verify 220104 before testing 70;
consult Observations.md for hardware results rather than inferring them from
the successful offline tests.

## Speed-55 research update (version 220103)

Prepared package: `main_hostpoint_trajectory_55.bin`. Relative to the retained
speed-47 package, only `main/mod_Trajectory.lua` changes: version 220103 and a
55 mm/s queue ceiling. Host speed 55 is restricted to the separately approved
`entry_speed55_toward_home` / `entry_speed55_to_hamilton` trials. The general
Cartesian cap stays 50; ordinary replay stays 40. Versions 220101 and 220102
remain supported at their respective 40 and 47 ceilings.

Publish this package using the same steps below, restart the program, and verify
220103 before a 55 trial. No hardware collision, acceleration or blending setting
is changed. Speed-55 geometry is identical to the recorded speed-47 geometry.
Offline testing is complete; check Observations.md for hardware execution status.

## Speed-47 research update (version 220102)

Prepared package: `main_hostpoint_trajectory_47.bin` in the repository root.
It changes only `main/mod_Trajectory.lua` relative to the prior trajectory package:
the queue speed ceiling is 47 mm/s and handshake/version is 220102. Other station
modules, zone -1, Stop behavior and gripper behavior are unchanged. This is an
application cap, not a change to the controller's hardware collision settings.

The host retains the ordinary 40 mm/s replay cap. Only the two explicitly approved
`entry_speed47_toward_home` and `entry_speed47_to_hamilton` variants request 47.
They use the exact 3 mm forward-entry geometry, reversed for the return. A legacy
220101 controller can still run speed 40, but rejects the 47 trial before upload
or consumption of its permission. Publish this package before testing 47.

Import the package into Offline Project, then use **Publish Offline Project to
Controller** (import alone is insufficient). Disconnect Flask while Works owns
the controller. After publishing, release Works, reconnect Flask, and start the
program fresh. Verify version 220102 before the first trial. The existing deployed
`main_hostpoint_trajectory.bin` is retained as the rollback artifact.

Hardware results belong in `../reports/trajectory_smoothing/Observations.md`;
preparation and offline tests are not a hardware run.

The Researcher page now offers **Taught Hamilton path → Replay method → Controller queue**.
It is unavailable until the controller has the new Lua program.

## Grouped replay update

The Researcher queue now coalesces adjacent, nearly straight segments before
upload. Both directions reduce to 132 MoveL commands (from 543/544); Hamilton
upload batches fall from 181 to 44. Endpoints remain unchanged. Deviation is
bounded to 0.25 mm and 0.1° from the quantized taught path, with ordered matching
to prevent loop shortcuts. Groups span at most 50 mm of original path / 10° yaw.
Significant corners/reversals and the first 5 mm / last 10 mm remain protected.
Every candidate is rechecked against joint/reach limits; live monitoring still
uses the original path. Speed and controller zone are unchanged.

45 offline tests pass, including executing both grouped routes through the actual
Lua source with mocked hardware. No Lua republish is required. Grouped hardware
smoothness has not been tested; the completed partial trial below used the
ungrouped queue. Comparison: `../reports/trajectory_smoothing/comparison.md`.

The host uploads the complete reviewed path in batches of three points, checks
the count and checksum, rechecks the starting pose, then explicitly executes it.
Lua feeds `MoveL` points into the native controller queue with one final
`MOVFINISH()`, rather than waiting for arrival after every point. External axes
are held at their starting values. The original station and gripper modules remain.

## Hardware trial — October 16, 2026, 14:40–14:45 PDT

- Published executor version 220101 was verified; all 543 points uploaded at speed 40.
- The first queued run stopped at 64.5%, after 246.7 seconds including upload.
  Controller Stop succeeded; no controller collision or joint-limit error appeared.
- Stop pose: X229.700, Y−9.540, Z253.710, Rz12.020. Hamilton was not reached.
- The XYZ-first path matcher can select the wrong yaw at overlapping segments.
  A rounded point on the intended segment reproduces a false 4.63° yaw error.
  Matching now considers XYZ and yaw together; the 2 mm/2° limits are unchanged.
- All 1,225 recorded trial samples pass the corrected matcher: maximum matched
  position error 0.028 mm, yaw error 0.005°. The exact triggering monitor sample
  was not captured; future stop messages include measured pose and both errors.
- Trial: `../demonstrations/return_path_trials_20261016_131713/trial_24915_26139.json`.
  Replay permission remains consumed; no automatic resume from the partial position.
- The startup torque report timed out; queue handshake, upload and movement worked.
  This separate reporting issue remains unresolved. Physical corner blending is
  still not validated; this version retains zone −1.

## Initial offline verification and deployment

- 24 queue/Lua tests pass after the matcher fix; the previous browser checks passed.
- Fixed the initial package's unzip failure: ZIP offsets now exclude the seven-byte
  `byrobot` prefix, matching the original vendor package. Reimport the rebuilt file.
- The actual Hamilton recording executed offline through Lua 5.1 in both
  directions: 543 points to Hamilton and 544 toward the demonstrated endpoint.
- Tests cover checksum/order errors, start drift, restart, upload timeout,
  controller backpressure, Stop, path deviation, joint limits, and old firmware.
- The initial deployment check found the executor absent. Publishing subsequently
  installed it successfully; see the hardware trial above for the latest state.

## Publish and test

1. Disconnect the robot in Developer view so Bioyond Works can own the connection.
2. In Bioyond Works, import `main_hostpoint_trajectory.bin` from the repository root
   into Offline Project, then **Publish Offline Project to Controller**.
   Use **Export and publish** to preserve the current controller project.
3. Release the Bioyond Works connection and reconnect the console. Stop/start
   the published program fresh; do not resume an old paused program. Empty-gripper
   preparation may close the jaws, as with the existing replay.
4. Verify the queue option is available. From the matched demonstrated endpoint,
   select Controller queue and explicitly start Return to Hamilton with the
   empty gripper, clear taught route, released arm and supervised E-stop.

Stop during queued playback asks the controller to stop its program; it does not
wait intentionally for the full path or automatically resume. If Stop cannot be
confirmed, motion is blocked pending controller inspection. A lost connection
may prevent the Stop request reaching the controller; this is not a safety-rated
watchdog. Validate controller Stop on a short clear segment before full-route use.

This version retains the existing `zone=-1` setting. It removes host round trips
between movements but does not claim continuous velocity through corners. Vendor
zone semantics and corner blending still need hardware validation. Joint/reach
checks and the existing path-specific workspace exception remain in effect.

## Developer notes

- Straight transfer uses `start-pruned` with `route: "straight"`, the exact
  candidate hash, and direction. A separate one-run permission binds the reviewed
  three-point artifact to its original recording and parent candidate. The host
  permits only vertical departure, level transfer and vertical arrival (up to
  300 mm vertical / 500 mm horizontal / 10 degrees transfer yaw), validates the
  entire IK path, and sends exactly three MoveL commands. These caps apply only
  to this explicit profile; ordinary queue segment limits remain unchanged.
  Monitoring stays 2 mm / 2 degrees around the newly approved path. A completed
  or failed attempt consumes its grant, with no automatic repeat.

- Z refinement uses `start-pruned` with `route: "vertical"` and an explicit
  `direction` (`to_hamilton` or `toward_home`). It reads the separate 75-point
  `vertical_smoothing/candidate.json` artifact and one-run permission, checks
  its baseline candidate hash, and sends exact points without regrouping.
  Only this reviewed variant admits near-vertical segments up to 200 mm:
  lateral endpoint drift <=0.25 mm and yaw change <=0.1 degree. Full IK and
  normal corridor/Stop checks remain active; horizontal limits stay 50 mm.
  No controller Lua republish is required. No hardware test of this variant yet.

- Approved shortened-route test: `/researcher/api/recorded-return/start-pruned`
  reads only `reports/trajectory_smoothing/pruned_middle/candidate.json` and its
  separate `replay_permission.json`. It requires matching candidate/source hashes,
  explicit one-run clearance approval, Hamilton start pose/joints, and speed 40.
  The exact 78 points are reversed and rechecked, never regrouped. Monitoring
  remains 2 mm / 2 degrees around the approved route. The original recording and
  its permission are unchanged; failure or completion consumes this test grant.
- `test_pruned_replay.py` runs the exact reversed artifact through real Lua 5.1
  with fake hardware, checking float-register transmission, one-run consumption,
  altered-file rejection, displaced start, cancellation and original-grant isolation.

- An explicitly requested return after a stopped Hamilton approach can use
  `/researcher/api/recorded-return/recover-start`. It requires the recording hash,
  reviewed waypoint index and readiness confirmation. The measured pose must
  match a taught waypoint within 0.15 mm/degree and the original IK branch.
  Recovery reverses only the taught prefix, validates every segment, and saves
  a separate `recovery_review_*.json` before controller preparation. It adds no
  direct approach and does not change the original recording or saved Home.
- Recovery and replay tests: `test_recorded_return.py` (17), queue/Lua tests (24),
  grouping tests (8). `compare_grouped_hardware.py` compares saved hardware trials
  over their shared path section; it never sends robot commands.

- Source: `mod_Trajectory.lua`; host: `../trajectory_queue.py`.
- Device 22; operations 1 begin, 2 append, 3 commit, 4 execute, 6 version handshake.
- SysVarI 7 is transaction ID; 17 is version 220101; 18 is state; 19 is submitted
  count (not physical arrival). Upload uses float registers 0–11 only.
- Checksums use integer metadata, avoiding float-register precision loss.
- Each transaction can execute once. Errors consume the path permission; no retries.
- Rebuild: `python operator_ui/build_trajectory_program.py`. The root manifest
  records baseline/output SHA256 and every preserved/changed archive member.
- Rollback: publish the untouched `main_hostpoint_trq.bin`, then stop/start fresh.
- Offline tests need `lupa==2.8` in addition to the console test dependencies:
  `python -m unittest discover -s operator_ui/tests -p test_trajectory_queue.py -v`.
