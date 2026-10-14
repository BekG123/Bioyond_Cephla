# ArUco / disk alignment update (2026-09-14)

## Wrist rotation fix (2026-09-16)

The live Align run reached Z300, then its first ~27-degree pure-yaw MoveL
outlasted the 120-second completion wait and 60-second settling window.
Pose readings showed the wrist still moving before it reached the first
waypoint; the generic recovery error incorrectly called this a connection drop.

Align now dispatches wrist-only rotation through `AlignmentGuard` and the
existing `rotate_to_rz` MoveJ service, at speed 30 in <=30-degree segments
(the service's existing joint-speed and wrist-segment caps). This replaces
the initial conservative speed-5 / 10-degree patch at the operator's request.
The observed ~82-degree turn now uses three segments rather than nine; the
speed parameter is six times higher, not a measured sixfold duration improvement.
XYZ is pinned to the measured pose. It checks height >=300, the envelope,
the measured IK branch and wrist headroom before rotation; it verifies both
TCP and J2/J3/J4 arrival afterward. Recovery, stale arrival and stop requests
abort without retry. Lift and XY translation continue using MoveL at speed 5.
The full future descent is still preflighted before any alignment movement;
this change does not validate the stored grip depth or change workspace bounds.

11 alignment tests and 27 transfer tests pass offline. This change has not
been tested on hardware. The running Flask process must be restarted while
robot motion is stopped to load the change; refreshing the browser alone
does not reload Python. The controller Lua program does not need restarting.

## Implemented, not deployed to the running console

- `autonomy.alignment_plan` validates lift, rotation, translation and descent
  with the measured J2/J3 branch and wrist headroom before returning any
  alignment waypoint. It checks the TCP envelope, not mesh collisions.
- Both disk and ArUco use `seq_align`. Lift precedes wrist rotation; motion
  is divided into short, arrival-checked steps. Recovery acknowledgements
  stop automatic continuation. No grip is part of alignment.
- ArUco Find filters candidates through that same path planner. Calibration
  and Find accept `marker_id` in their existing HTTP request bodies.
- Calibration reloads on-disk marker sizes, includes camera tilt in centering,
  and rejects clipped outlines or optical distances outside 205–240 mm.
- Find requires object-offset calibration and matching camera/claw stamps.
- Descend checks jaw clearance and the vertical path before starting; existing
  held-object transfer retains its separate holding checks.

## Current plate: read-only planning result

At TCP (293.115, 56.588, 270.453), Rz -6.443, measured joints approximately
(231.854, 82.5335, 52.3468, -141.3234), ID 1 is visible at about 218 mm.
Using the operator-measured 85 mm width provisionally in memory:

- Near width approach crosses J2 +93 degrees on the current branch.
- Far width approach exceeds extension tracking margin.
- A length approach is kinematically possible but requires about 128 mm
  jaw opening, beyond the 88 mm available.

This is not a rack collision analysis. The broad diagnostic envelope used
offline was NOT applied to hardware. No plate calibration was persisted,
no motion was issued, and the running backend was not restarted.

## Verification and remaining work

7 alignment regressions, 27 transfer tests, 15 pickup tests, 1 marker-size
test, and vendor disk math self-tests pass. Syntax and diff checks pass.
The older `tests/test_offline.py` harness is not green: its dead torque and
pose/joint-inconsistent fixtures are rejected, and its expected success
results cause a later KeyError. Update those fixtures before live deployment;
do not weaken the guards to satisfy them.

Before physical use, reload only with a safely disabled/idle robot, validate
marker-to-object calibration and actual jaw clearance, and commission the
full swept volume. The current plate pose has no validated width approach.
