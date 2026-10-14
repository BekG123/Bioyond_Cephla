# IC reference and alignment preview

## Later, at the hardware

1. Use stable lighting. Manually align the open jaw contact faces with the chosen
   plate edges at a repeatable hover height. Stop moving before capture.
2. In the Flask console, connect the robot for pose reads and enable the camera.
   Open **IC visual alignment — reference capture and preview** beside Align.
3. Choose a label and 3–30 images (default 10). Automatic ROI surrounds both disks.
   Alternatively enter a plate-only rectangle as `x, y, width, height` in the
   native camera image coordinates. Exclude jaws and unrelated background.
4. Check the manual-alignment and plate-region acknowledgements, then click
   **Capture reference batch — no movement**. Progress appears in the normal
   sequence log. The batch rejects robot motion above 0.1 mm / 0.1 degrees,
   plate-image movement, insufficient texture and dark/saturated regions.
5. Review the green region in the saved reference. Capture a new batch with a
   custom rectangle if it contains jaws or background features that would
   dominate tracking. A correct reference must be physically verified by you.
6. After a small manually controlled pose change, stop moving, select the
   reference, and click **Compare current image — no movement**. The overlay and
   numbers show the image difference. Stop capture/preview with **Stop**.

Both actions receive only camera capture and pose-read interfaces. They never
call motion, change controller settings, or publish a robot grasp target. The
shared Runner prevents simultaneous GUI motion while capturing/matching.
Do not jog using a separate controller during capture. Telemetry and images
are sequential, not hardware synchronized.

## What is implemented

True inverse-compositional Lucas–Kanade on a four-parameter similarity warp:
translation, in-plane rotation and uniform scale. The image pyramid reduces
sensitivity to initial offsets. Template gradients, steepest-descent images
and the Hessian are cached. Updates compose as `W = W @ inverse(delta_W)`.
This is not OpenCV ECC, neural-network training, or a 3D pose/depth solver.

Both detected disks initialize the warp when available; otherwise the numerical
solver starts near identity. Brightness mean/contrast normalization tolerates
moderate gain/offset changes but cannot recover an unilluminated plate. The
template region needs enough structure to constrain all four parameters.
Large perspective changes, occlusion, reflections, moving backgrounds and
repetitive features can cause rejection or a false local match. Review the
overlay and validate on actual offset poses before any automatic motion use.

Reference batches retain every raw PNG, capture timestamps, pose before/after,
camera identity, file hashes, ROI, and per-frame stability results. The template
is the median of the accepted stationary images. Only complete batches become
selectable/active. Files are in `Align/references/` (ignored by Git).
The last active reference persists across app restarts. Failed batches remain
marked failed and never replace the previous active reference. Camera serial,
resolution, reference image hash and saved calibration signatures are checked.
A physical camera/lens/mount change requires a new reference even if its serial
and configuration files are unchanged.

## Interpreting output

- Warp direction: **reference image pixels to live image pixels**.
- Shift: native-pixel displacement of the reference ROI center; X right, Y down.
- Rotation: image degrees, positive clockwise. This is not robot Rz.
- Scale: apparent image-size ratio, not an independently measured Z distance.
- Normalized RMSE/correlation: photometric image agreement, not millimeter or
  depth accuracy. Default match gates: correlation >=0.90, normalized RMSE <=0.45,
  rotation within 15 degrees and scale 0.8–1.25; numerical optimization must converge.
- `image_aligned`: accepted match, center displacement <1 px, rotation <0.2 degrees,
  scale difference <0.003. These are initial image-space tolerances, uncommissioned.
- `robot_alignment_verified` and `motion_commanded` remain false.

Numerical iterations per pyramid level are bounded to avoid a hung image request;
that is separate from Fast calibration's continuous physical convergence loop.
Compute time excludes capture, initialization/disk detection and robot movement.
The median template's known jaw relationship comes from the operator, not IC.

## Still required before robot feedback

Validate image-to-robot correction signs, scale and camera-to-gripper offsets
using known small moves. Preserve guarded motion, fresh-image checks and
independent physical jaw/plate verification. IC must not substitute image
similarity for calibrated millimeter clearance or proof of a secure grip.
The existing `motion.py` Align stage remains unchanged and separate.

Algorithm source: [Baker and Matthews, Lucas-Kanade 20 Years On](https://publications.ri.cmu.edu/lucas-kanade-20-years-on-a-unifying-framework).

## Offline validation (2026-09-19)

Sixteen numerical/reference/API tests pass. The related calibration, alignment,
pickup, transfer and original-routine suites bring the checked total to 112.
JavaScript event/rendering checks pass in an isolated DOM test. Browser screenshot
QA was unavailable in this session; no live camera or robot test was performed.

Replay of the 29 previously captured normally lit XY views accepted 29/29 image
matches, using saved disk detections for initialization. Minimum correlation was
0.99918; median IC computation was 17.47 ms on this machine. This excludes camera
capture/disk detection and is not a robot alignment-speed or accuracy benchmark.
The first old capture served only as an offline template, not as an approved
gripper reference. No active reference was created. Results and selected overlays:
`operator_ui/reports/ic_offline_20260919/`.

Reproduce with a fresh output directory:

```powershell
py -B "Pick and Hold/Align/offline_check.py" operator_ui/datasets/depth/plate_xy_20260918_v2 --output operator_ui/reports/ic_replay_new
```
