# Image-based XY correction in Flask

Console > Grab pipeline:

1. **Preview plate edges (no motion)** captures a fresh frame and displays
   the fitted plate sides/corners, image center and correction arrow.
2. Verify that the entire fitted outline belongs to the intended plate.
3. Set **Camera-to-plate distance** to the approximate commissioned optical
   working distance (205-240 mm; the initial field is 205). This is NOT TCP Z
   and is not inferred from robot Z. It scales only the XY feedback gain;
   no height or grasp depth is inferred from it.
4. **Center plate (edges)** requires explicit confirmation of the outline,
   empty gripper, clear XY swept volume, and supervision at the E-stop.

This first implementation corrects X/Y only. Z and Rz remain fixed. The image
angle is displayed but does not command wrist rotation. It neither descends,
grips nor publishes a grasp target. Starting motion-centering clears the old
grasp target, since moving the camera invalidates that workflow's assumptions.
The preview alone preserves an existing target.

## Mapping and verification

`edge_center.CameraMapping` loads the saved camera fit plus vendor native
resolution, intrinsics and distortion. It does not run marker or circle
detection. The vendor math selftest must pass and camera-fit metadata must be
valid. Image-center and plate-center points are undistorted, differenced,
scaled by optical distance/u_scale, mirrored and rotated by Rz + camera yaw.
Camera lever-arm and tilt offsets cancel for this fixed-height/fixed-yaw
difference. This is an approximate local feedback mapping, not a newly
commissioned absolute plate/gripper pose.

The sequence confirms two stationary outlines before its first move. It checks
the complete predicted centering path and each executed segment using the
current joint branch, J2/J4/singularity guards and enabled motion box. First
move is <=2 mm; subsequent moves <=5 mm; gain 0.7; speed 5; MoveL only.
After substantial steps, the observed image response must match the commanded
XY direction and approximate magnitude. Failure stops without retry. The
optical-distance estimate never justifies overriding the observed response.

Every frame must show one unambiguous supported four-sided outline. Stationary
center changes >8 px, side-size changes >5%, angle changes >2 degrees with
fixed wrist, lost edges, wrong motion response, increased error, stale/recovered
acknowledgements, missing telemetry or external pose changes stop the loop.
The initial empty-gripper telemetry check complements, not replaces, operator
confirmation. No errors are cleared and no robot is enabled automatically.

Success requires TWO fresh centered views: radial offset <=8 native pixels
AND estimated offset <=0.75 mm. The result says `centered: true` and
`grasp_target_created: false`. Limits: 18 views, 120 seconds checked between
operations, 70 mm total XY travel. Software STOP is between commands; hardware
E-stop is required for an immediate stop. These are not collision-mesh checks.

## API and deployment

- `POST /seq/preview_plate_edges {}`: no robot connection/motion required.
- `POST /seq/center_plate_edges`: JSON booleans `confirm`, `cell_clear`,
  `empty_gripper`, `outline_verified` all true, and `camera_distance_mm`.
  Never supply confirmations without the operator's fresh approval.
- Shared `/seq`, detection panel and `/teach_view` display progress and overlay.
- Only restart Flask while no sequence is active; do not restart the Lua
  robot program. Reload the browser after loading the Python changes.

Offline coverage: pixel mapping/mirroring/rotated wrist, wrong resolution,
first-move response check, fixed Z/Rz, no grasp commands/target, ambiguous/lost
edges, initial agreement, limits, telemetry, stale/recovered arrivals, STOP,
budgets and Flask route confirmations. The detector has separate synthetic
image tests and was tested on the real saved plate image. Closed-loop hardware
centering still needs a supervised commissioning run.

```
py -m unittest discover -s operator_ui/tests -p test_edge_center.py -v
py -m unittest discover -s operator_ui/tests -p test_plate_edges.py -v
```
