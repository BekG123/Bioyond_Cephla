# Supervised pickup verification

This stage does not run automatically after Grip. The operator explicitly
approves a 2–5 mm vertical lift at speed 5 while at the E-stop. No hardware
testing was performed during implementation. Restart the operator backend
only when the robot is safely idle and not holding a plate, then refresh the
browser. Do not restart the controller program to deploy this UI change.

## Workflow

1. Commission/enable the workspace envelope. Use the existing plate calibration,
   alignment, descent and Grip stages. A torque crossing without a position
   stall now returns `ok:false, gripped:false`.
2. In **5 Verify pickup**, enter the rigid plate marker ID and measured signed
   marker-plane-to-plate-center Z offset. Confirm plate XY/yaw calibration and
   that the plate is level. The existing per-ID dx/dy/yaw calibration is reused.
3. Click **Verify pickup: approve small lift…** and approve the explicit motion
   prompt only with a clear vertical path and an operator at the E-stop.
4. The backend requires Grip evidence less than 120 seconds old, not invalidated
   by another command. Fresh E1 must be within 0..28 mm, torque below -100 and
   position more than 0.15 mm above the confirmed close command. These torque
   values are controller units, not Newtons.
5. It captures a fresh before image, executes one guarded linear lift, checks
   fresh grip telemetry, and captures an after image. Marker motion must match
   the commanded lift within 1.5 mm, with <=2 mm lateral and <=2 degree yaw change.
6. Inspect BEFORE/AFTER images and the actual plate. Explicitly confirm it is
   lifted, secure and level, or reject. The Runner keeps exclusive ownership;
   other normal commands are blocked. STOP and disable remain available.
   Confirmation expires after 120 seconds; no automatic return/release occurs.
7. Approval triggers another fresh image/pose solve, joint query, E1 query and
   stationary-pose check. Only then is `pickup_verified:true` returned. Export
   the post-grasp snapshot within 30 seconds. No transfer is launched.

## Constraints

- No vision fallback is invented. Missing/ambiguous/occluded marker or missing
  calibration refuses verification. Existing camera limits are retained:
  optical distance 205..240 mm and marker within 5 mm of view center. A held
  plate may not be visible within this region. If so, commission another
  observation arrangement before using this stage; it does not reposition the
  camera/arm automatically while holding.
- Pose is XYZ+yaw with an operator-confirmed level-plate assumption. Roll/pitch
  are NOT measured. `plate_relative_to_gripper` uses the calibrated claw XY
  midpoint at TCP Z, oriented with TCP yaw; this is a defined reference frame,
  not a claim that actual jaw-center Z has been calibrated.
- Pose/joint/E1 acquisition is sequential, bracketed by stationary checks, not a
  simultaneous hardware latch. Fresh acquisition must complete within 10 seconds.
- Snapshot expires after 30 seconds and another admitted mutating command or
  STOP invalidates it. Exported JSON is historical evidence, never a reusable
  motion authorization; a future transfer consumer must reacquire live state.
- Timeout/recovery/fault rejects verification without repeating the lift or
  changing the gripper. Inspect the physical state before the next command.
- Draft/snapshot state is in memory. Images use unique local capture names.
  Server restart discards approval state; do not restart while holding a plate.

## Interfaces and tests

- `POST /seq/verify_pickup`: explicit confirmations, marker ID, lift, calibrated Z offset.
- `GET /pickup/state`: state and short-lived snapshot.
- `GET /pickup/image/before|after`: images only during pending review.
- `POST /pickup/confirm`: matching one-use token plus explicit boolean answer;
  this endpoint itself never commands hardware.

`py operator_ui/tests/test_pickup.py` uses fake services only. Tests cover
confirmed handoff, absent approval/envelope, bad telemetry, stale evidence,
missing marker, non-following plate, rejection, motion recovery (no retry),
wrong token, expiry and the torque-only grip regression.
