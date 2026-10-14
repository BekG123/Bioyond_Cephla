# ArUco transfer and Squid scene

The existing Flask console is retained. The new **ArUco transfer** tab runs
one operator-armed detect/pick/place/retract cycle, not a background loop.
It does not control the Squid stage, doors, clamps, imaging or interlocks.
Keep a human at the physical E-stop. Do not use unattended until the cell
has been commissioned and independent safety/interlock controls installed.

## Commission first

1. Match the marker dictionary (4x4_50), physical printed size, object ID,
   marker-to-grasp XY/yaw/size calibration and camera/claw model versions.
   Reused stickers on another object require recalibration. The size is
   read from the existing calibration; it is not assumed to be 20 mm.
2. Verify the marker-to-grip TCP Z offset on this plate/support. Enter it
   explicitly; no fallback to another object's/global disk depth is made.
3. Teach the destination **TCP** X/Y/Z/Rz at correct plate seating height.
   These are not plate-center coordinates (the claw has a long offset).
4. Set and enable the workspace envelope. Verify a collision-free swept
   route for the entire arm, claw and carried plate, including the vertical
   withdrawal from Squid and all wrist rotations. Travel Z must be >=300 mm,
   above current Z, and >=25 mm above both engagement poses; those numerical
   checks do NOT establish clearance from a tall microscope.
5. Squid must be stationary, plate accessible/released, destination support
   empty/ready, gripper empty, and a human at E-stop. Position the eye camera
   so the marker is within 5 mm of view center at 205–240 mm optical distance.

## Use

- Fill marker ID, verified grip offset, travel height and destination.
- **Detect & preview route** takes three fresh observations and validates
  a full route without robot/gripper motion (telemetry jobs still run).
  The cyan line in 3D is the TCP path, not the swept volume.
- Review the route and commissioning checklist; **Start one transfer**
  prompts for fresh confirmation and detects again. It does not reuse a
  cached preview target. Browser-saved fields never save confirmation.
- Sequence logs show failure phase. Stop cancels between commands, not an
  in-flight motion; use the hardware E-stop for immediate stopping.
- On errors or ambiguous holding, inspect before retrying. No autonomous
  enable, error clearing, homing, fault retry or recovery motion is added.

## Guards and limitations

Requested marker only; duplicate same-ID detections rejected. Three centered
observations must agree within 2 mm in 3D and 2 degrees. Repeats reject jitter,
not systematic camera bias. Both planar IK branches are considered using live
joints. Full linear segments are sampled at <=2 mm / 1 degree for envelope,
singularity margins, J2 lower limit and J4 preferred headroom (normally +/-150).
These are additional guards, not a complete controller/collision model.

Moves recheck preflight and measured arrival; missing feedback, stale/false
acknowledgements and connection recovery fail the transfer. Travel legs are
split into short commands. Descents use the existing torque guard; ANY breach
aborts the transfer even if the old manual sequence classifies it as drift.
No early grip/release. Grip requires torque AND position stall, with a span
sanity check; holding torque is checked during carry and descent. Torque alone
does not certify correct grasp or final seating. Visually verify commissioning.

## Squid CAD

Updated 2026-09-14: the GUI now uses the supplied `Squid+ with C-mount and
4 position turret.STEP`, converted to `static/models/squid_plus_cmount_4turret.obj`.
Its companion JSON records the source checksum, units, bounds and tessellation.
The operator's updated default footprint-center placement is X=75, Y=600,
Z=0 mm, yaw=0 degrees, CAD up=Y (read from the GUI on 2026-09-14).
This visual placement still requires physical registration.
The new model uses its own browser storage key (`bioyond-squid-plus-v1`).
The draggable preview uses blue J1, orange J2, green J3 and purple J4 sections;
the current-pose arm remains white. The earlier public model is retained on
disk for reference but is no longer loaded by the GUI.

The colored preview has Z +/- buttons and a height slider. Rotation dragging,
typed targets and height controls share bounded kinematics: J1 0-400 mm,
J2 +/-93 degrees, J3 +/-180 degrees, J4 +/-150 degrees using current settings,
plus the existing folded/extended reach margins. Joint angle winding is
preserved and intervening joint sweeps are sampled. Rejected targets retain
the last accepted preview pose. These checks model joint/reach constraints,
not contact dynamics or collision geometry. Offline references are illustrative;
initialize from measured joints before execution. Preview controls send no
hardware commands. Additional manual limits live in `static/preview_config.json`.

### Previous model provenance

Source: [Cephla Squid](https://github.com/Cephla-Lab/Squid), README's original
Squid CAD folder. Asset: original inverted Squid with laser launch and an
additional camera, not verified as the installed cell revision. Source URL,
SHA-256, units, mesh tolerance and bounds are in
`static/models/squid_original_inverted.json`. `convert_squid.py` rebuilds the
OBJ using the installed FreeCAD, without contacting the robot.

3D placement controls normalize CAD to footprint-center/bottom, then apply
robot-frame X/Y/Z and yaw in mm/degrees; an up-axis selector supports CAD
orientation. Initial placement is illustrative. Values are saved only in
this browser. They are not consumed by the motion planner. Existing robot
CAD calibration also needs registration before use as a geometric twin.

## Offline verification

`py -B operator_ui/tests/test_transfer.py` — fake service/camera, no hardware.

`py -B operator_ui/tests/preview_server.py` — port 5003, isolated fake-hardware
browser QA. All physical-control POST routes blocked. Production remains
`py operator_ui/app.py` on port 5002; restart only when robot activity is
stopped and its physical state is known. Do not restart/enable the controller
program while holding a plate.
