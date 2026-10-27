# Offline 48/96-well plate pose prototype

Detect a plate's rim and well grid, recover its camera-relative pose, and overlay two virtual circles. **No hardware access or live UI integration.** Existing two-disk calibration, alignment, descent and grip remain unchanged.

## Actual taught disks projected onto the plate

### First live motion commissioning

**Current commissioning mode:** `projected_disk_trial.Perception` uses `multiview_rim.commissioned_tracker`, with two frozen nearby views built from hash-checked stationary samples. Both are registered directly to the original mapping; no frame-to-frame updates occur. At least two views must pass the existing per-registration quality gates, with <=0.8 px disagreement over virtual disk outlines and <=2 px across the plate extent. The pilot requires three consecutive observations agreeing within 0.25 mm; vision-only rejections reset this count during a 20-second stationary acquisition window. Faults, Stop, pose changes and inconsistent accepted measurements stop immediately. An expired post-move check remains a failed move verification, never a successful calibration. On 2026-10-26 this advanced one 2 mm step, then stopped. A separately approved 20 mm upward camera-view trial reached Z268.025; all five subsequent cross-view checks rejected. This remains experimental and is not a completed or production-ready 48-well calibration.

**Latest implementation and physical limit, 2026-10-26:** rim tracking now rectifies the current image into the fixed reference frame using a descriptor-derived seed before bidirectional LK refinement (41 px window, pyramid level 1). The seed is not an accepted pose; final agreement, displacement, residual, coverage and clipping checks still apply. Nineteen focused tests and 21 comparison images passed. A physical retry passed the previous failure viewpoint but stopped at the next one with 22/38 consistent matches (57.9%). Full calibration remains incomplete; do not treat the stationary tests as validation over the full approach. Evidence: `operator_ui/reports/projected_disk_pilot/rectified_rim_20261026_verified/` and motion logs `20261026_202425_7bf7e8c6.jsonl`, `20261026_202435_297796f5.jsonl`.

**Rim refinement fix, 2026-10-26:** the stopped-view failure reproduced in five stationary frames. Increasing the Lucas–Kanade window from 21 to 31 px recovered consistent rim tracks. Reducing its maximum pyramid level from 3 to 1 also retained the synthetic changing-well-content regression; descriptor matches already initialize the displacement. The fixed reference and all acceptance thresholds remain unchanged. All 15 comparison images passed: five earlier frames, five failure-pose frames and five fresh held-out frames. Fresh agreement was at least 78.5%, with RMS at most 0.693 px. The old refinement rejected all ten failure-pose/fresh frames. This is stationary image validation, not completed physical calibration. Evidence: `operator_ui/reports/projected_disk_pilot/rim_refinement_20261026/comparison.json`; reproduce with `benchmark_rim_refinement.py` and `validate_rim_refinement.py` under `operator_ui/`.

**Tracking improvement, 2026-10-25:** after the second step's visual failure, the arm remained stopped while testing rim masks, excluding well interiors, contrast normalization and subpixel refinement. The selected `Tracker(mode='rim')` uses a 35 px inward band at 1200 px preview width, CLAHE, stricter mutual SIFT ratio 0.6, and forward/backward Lucas–Kanade refinement. The original fixed reference is retained; there is no incremental reference reset. The 65% agreement, 0.8 px RMS, distributed-coverage, clipping, minimum-match and local scale/orientation checks remain. The agreement denominator includes ALL original mutual descriptor matches, including tracks discarded during refinement.

Five fresh pose-monitored validation frames passed at 67.0–73.3% agreement, 0.59–0.65 px RMS and 89–94% spatial coverage; the previous tracker failed all five. The integrated implementation then passed five more camera frames at 68.0–73.7% agreement and 0.57–0.62 px RMS. Robot feedback was disconnected during that second camera-only batch, so it is not evidence of verified robot stationarity or motion readiness. Reports: `operator_ui/reports/projected_disk_pilot/strict_matches_validation/validation.json` and `rim_live_validation/observations.jsonl`.

The XY pilot now explicitly selects rim mode. Three new regression tests cover independently changing plate interiors under a known transform, blank/unrelated/clipped images, and the five saved real validation frames. The 11 focused tracker/pilot tests pass. No physical movement was retried during these tracking experiments. This improves tracking at the current stopped viewpoint; performance across a completed calibration remains untested. Launch the camera-only display with `--tracking-mode rim`; its status now shows the agreement percentage.

`operator_ui/projected_disk_trial.py` prepares and runs **one supervised 2 mm XY pilot at speed 5**, with Z and wrist fixed. It uses projected disk **centers** and the existing vendor XY camera transform. It does not feed virtual radii into the depth solver, run full calibration, publish a grasp target, align, descend, or operate the claw. Two fresh stationary observations are required before and after the move. The measured image response must agree with the physical movement and reduce centering error; any failure stops without retry.

The loaded Flask endpoint is `POST /seq/projected_disk_pilot`, using the existing Runner and GuardedService for sequence exclusivity, Stop, controller checks, IK/workspace, and arrival validation. It requires explicit `confirm`, `cell_clear`, `empty_gripper`, and a reviewed `expected_start` pose. These attestations must come from the operator. Logs append to `operator_ui/reports/projected_disk_pilot/*.jsonl`. A passing pilot is not full calibration or collision validation.

Prepare without movement with `operator_ui/projected_disk_trial.py --preview-output <path.json>` using the project Python. Five tests in `operator_ui/tests/test_projected_disk_trial.py` cover confirmations, the 2 mm bound, unchanged height/wrist, successful response, lost vision and reversed response stopping without retry. The first proposal at Home is approximately X288.967/Y60.900/Z248.020/Rz−3.88. Physical execution awaits the operator's current empty-gripper/clearance/E-stop confirmation.

The first physical pilot passed on 2026-10-25: X289.970/Y62.630 to X288.967/Y60.900, with Z248.020 and Rz−3.88 unchanged. The image response agreed with the commanded 2 mm XY move; no controller errors were reported. It stopped after this single move, with no grasp target. Evidence: `operator_ui/reports/projected_disk_pilot/20261025_001446_9570c2a1.jsonl`. This validates a local XY response, not complete centering, depth/yaw calibration or alignment.

The second authorized 2 mm step reached X287.994/Y59.153/Z248.020/Rz−3.88, then stopped on inconsistent feature matches. No controller errors were reported. Do not count this as another passed calibration step: post-move visual verification failed. Log: `operator_ui/reports/projected_disk_pilot/20261025_001631_3e524e35.jsonl`. A subsequent stationary diagnostic found 214/377 consistent matches (56.8%, below the existing 65% requirement), confirming a tracking limitation. It saved `after_second_step/raw.jpg`, `matches.jpg`, and `diagnostic.json`. No further motion or threshold relaxation was performed.

The operator measured the original plate at 15 mm tall and the well plate at 20 mm tall. The +5 mm top-plane offset is recorded in the physical model, conditional on equal supporting heights. It is not applied to descent; gripping-edge height remains unverified.

`live_projection.py` adds a **read-only live camera check**, using mutual SIFT correspondences and a projective fit to the annotated 48-well reference. It sends only GET `/frame` and GET `/state` to the existing Flask console. It has no robot executor. Freshness, distributed inliers, residual, local scale/orientation and clipping checks reject unsupported observations; a rejected frame displays no old circles. This is local reference tracking, not general plate identification or metric calibration. Large-left/small-right correspondence was confirmed by the operator; autonomous orientation recognition remains unresolved.

```powershell
.venv-realsense/Scripts/python.exe -B "Pick and Hold/Align/plate_pose/live_projection.py" --reference operator_ui/reports/plate_projection_taught_48/result.json --output operator_ui/reports/plate_projection_live_check --samples 3
# Optional local live display; stop this process to stop the display server.
.venv-realsense/Scripts/python.exe -B "Pick and Hold/Align/plate_pose/live_projection.py" --reference operator_ui/reports/plate_projection_taught_48/result.json --output operator_ui/reports/plate_projection_live_view --serve 5013
```

Three stationary physical-camera observations passed with 508–511 inliers and 0.51–0.53 px registration RMS at 1200 × 800 preview resolution. No arm movement occurred. The JSONL records each observation and the latest JPEG is replaced instead of accumulating unlimited image files. This does not verify absolute annotation accuracy, depth, camera-to-arm mapping, loaded motion or descent. The plate top-plane height relative to the original reference and the gripping-edge relationship still need to be established before live motion.

`project_taught_disks.py` segments the **real printed disk outlines** in the archived successful calibration image `teach_fast_20261017_035215_6e7d8a12_0001.png`. It transfers those contours to the current 48-well plate with a four-corner homography (scale, rotation and perspective), replacing the illustrative circles for this preview. Equal outer dimensions are the operator's assertion; this pixel mapping needs no invented millimeter dimensions.

```powershell
.venv-realsense/Scripts/python.exe -B "Pick and Hold/Align/plate_pose/project_taught_disks.py" --annotations "Pick and Hold/Align/plate_pose/taught_projection_annotations.json" --output operator_ui/reports/plate_projection_taught_48
.venv-realsense/Scripts/python.exe -B "Pick and Hold/Align/plate_pose/test_taught_projection.py"
```

Results include `source_overlay.jpg`, `target_overlay.jpg`, and `result.json` with source image hashes, measured outlines, normalized plate coordinates, annotations, and the alternative 180-degree correspondence. Corners were manually annotated from visible edges, extrapolating across rounded/chamfered corners. They are **provisional and not physically reviewed**. The newest frame did not pass automatic grid detection; the overlay records manual corner correspondence and `grid_tracking_valid: false`. A failed grid fit never becomes a successful automatic detection.

This is an inspection overlay only. It does not estimate depth, resolve plate orientation, correct lens distortion or account for differences in feature-plane height. It is not connected to the robot. Do not use projected circle radii as independent measurements in the old disk-distance solver. Five projection tests cover measured disk geometry, perspective/round-trip accuracy, bad seeds, mirrored/degenerate corners, and projective-horizon rejection.

## Current 48-well image test

The operator confirmed the physical plate is 48-well (6 × 8). `grid_preview.py` detects well rings directly, fits their grid with a projective transform, and draws a pixel-only preview without relying on the transparent rim. On the saved current image it found 48 ring candidates and retained 43 consistent centers, with a 6.95 px image-fit RMS at 3072 × 2048 resolution. This is grid consistency, not metric pose accuracy.

```powershell
.venv-realsense/Scripts/python.exe -B "Pick and Hold/Align/plate_pose/grid_preview.py" --image operator_ui/reports/plate_projection_current/current_plate.png --output operator_ui/reports/plate_projection_48
.venv-realsense/Scripts/python.exe -B "Pick and Hold/Align/plate_pose/test_48.py"
```

The green dots are measured centers; the green lines are the fitted grid. Orange/blue circles have **illustrative positions and radii in grid intervals**, not the original taught reference mapping. The symmetric grid does not identify A1. No distance, metric pose, alignment command, descent or grip is produced. The metric alignment adapter explicitly rejects this pixel-only result.

The image detector assumes a largely visible, moderately tilted plate filling much of the view, with visible rings. Its Hough radius range is a pixel search heuristic, not a physical diameter. Gross perspective, occlusion, poor contrast and incompatible grids reject the estimate. More real images are needed to establish robustness.

`plate_48_pending.json` records the confirmed layout and leaves unmeasured physical dimensions, orientation and grasp mapping unset. `vision.py` now supports measured 6 × 8 models as well as 8 × 12 models. `demo.fixtures(48)` supplies **synthetic-only** geometry for pose regression; never copy those dimensions into the physical plate record.

The user's reference image names **Falcon 353296**; this is a candidate, not confirmed identification of the physical plate. See [candidate record](falcon_candidate.json). Corning lists it as a white flat-bottom plate. Synthetic geometry and its single chamfer are illustrative, not verified product geometry.

## See the result

Open [offline gallery](demo_output/index.html). It includes three generated views, overlays, known ground-truth errors and JSON records. Green dots are measured well centers; orange/blue outlines are virtual landmarks. The model estimates pose **before** drawing them.

Run from the repository root using the existing Windows environment:

```powershell
.venv-realsense/Scripts/python.exe -B "Pick and Hold/Align/plate_pose/demo.py"
.venv-realsense/Scripts/python.exe -B "Pick and Hold/Align/plate_pose/test_offline.py"
```

On Linux, use Python 3.10+ with NumPy and OpenCV (`python -m pip install numpy opencv-python`), then replace the interpreter above with `python`. Tested locally with NumPy 2.2.6 and OpenCV 4.14.0.

For a local saved image:

```powershell
.venv-realsense/Scripts/python.exe -B "Pick and Hold/Align/plate_pose/offline.py" --image image.png --model plate.json --camera camera.json --output offline_result
```

Demo-generated `model.json` and `camera.json` show the schema but **must not be used as a real camera calibration**. The command writes `result.json` and, on a valid estimate, `overlay.png`. Rejections return exit code 2 with a reason. Optional `--orientation-template patch.png` uses a previously captured rectified orientation patch. Optional `--alignment-context context.json` runs the existing pure alignment planner; see `demo_output/alignment_context.json` for a synthetic schema example.

## How it works

1. Undistort using the matching image resolution and OpenCV intrinsics.
2. Detect an unclipped, high-contrast outer quadrilateral. Rectify candidate orientations into the modeled plane.
3. Require an orientation cue and at least 40/48 or 80/96 uniquely matched wells spanning every expected row and column. The symmetric grid alone cannot distinguish a 180-degree reversal. Supported cues are a single chamfer (synthetic fixture) or a rectified appearance template, e.g. molded lettering/logo. No OCR is implemented.
4. Fit planar PnP to measured well centers, compare alternative solutions, refine, and reject excessive reprojection error. The rim establishes correspondences but is excluded from the metric fit because a base skirt and well tops need not be coplanar.
5. Project physical circle outlines through the fitted pose. Under perspective these can be ellipses. Virtual radii do not enter the old radius-to-distance solver.
6. For an optional offline alignment preview, calculate `T_base_tcp = T_base_camera * T_camera_plate * T_plate_tcp`. Then call the existing `autonomy.alignment_plan`, retaining its IK branch and workspace checks. Reject unsupported tool tilt. No descent or grip is planned or executed by this adapter.

Transforms map from the right-hand frame name into the left-hand frame name. All translations use millimeters. Plate x follows columns, y follows rows, z is the feature-plane normal; camera axes follow OpenCV. The camera-in-base transform must correspond to the image exposure, not a later robot pose. An appearance overlay does not establish a camera-to-robot transform or obstacle clearance.

`reference_mapping.map_reference` maps sampled outlines of the original two disks through an annotated coplanar reference quadrilateral and fits their metric circles. It preserves perspective rather than scaling pixel radii. The original reference plane must then be registered to the new plate's desired grasp frame. Demo circle locations are illustrative until that measurement exists.

## Validation and limits

### 48-well fixed-focus commissioning (2026-10-26)

`grid_pattern.py` adds a separate image-only tracker for the current 6 × 8
plate. Measured well centers initialize registration; alternating sets of well
rings independently match the frozen image. It requires distributed support
from at least 40 wells, image correlation ≥0.8, and agreement within 0.8 preview
pixel over the virtual disk outlines / 2 pixels over the plate extent.

`commissioned_grid_tracker` uses five hash-checked stationary frames captured
after the approved rise to Z268.02. Their median is registered directly to the
original taught reference. Both stages' alternative transforms are composed
and checked together; the reference never updates during motion. Symmetric
well patterns still do not identify A1, and no metric depth is inferred.

The supervised `/seq/projected_disk_pilot` accepts explicit
`tracking_mode: "anchored_grid"`; the existing rim mode remains the default.
Each pilot requires three consistent observations before and after one 2 mm
XY move at speed 5. Rejection stops progression. This does **not** publish a
full calibration, alignment, descent or grip target. Tests are in
`operator_ui/tests/test_grid_pattern.py`; raw frames and motion JSONL logs are
under `operator_ui/reports/projected_disk_pilot/`.

The anchored tracker may initialize from a coarse, distributed rim-texture
fit when available; this fit is never accepted as a pose. The final well
pattern and composed-transform gates still apply. Explicit `burst_frames: 5`
captures five fresh frames while checking arm stillness, rejects repeated stale
frames, and registers their median. Median PNGs and source hashes are logged.
Optional `finish_centering: true` reduces the final steps below 2 mm and verifies
an estimated XY residual ≤0.75 mm twice while stationary. Even that result is
only XY centering, not height calibration or a validated grasp pose.

Three synthetic views (rotation, tilt, noise) recover all 96 wells. Errors and input assumptions are saved in `demo_output/summary.json`; **synthetic errors are not real-world accuracy claims**. Tests cover pose accuracy, wrong resolution, bad intrinsics, missing/ambiguous orientation, incomplete grids, grid outliers, original two-disk photo rejection, virtual landmarks not affecting pose, reference mapping, and the existing IK/limits planner.

This first detector assumes strong rim/well contrast and largely visible wells. It has not been validated on the physical Falcon plate, transparent plastic, lids, liquid-filled wells, reflections or the robot claw occluding the rim. Rim-plane mismatch can also prevent correspondence acquisition even though only wells enter PnP. Wrong physical scale can give a low reprojection error and still give wrong distances. A stock product photo has no usable camera calibration for metric validation.

Next real-data step: save actual plate images and a measured/confirmed feature model, camera intrinsics, a unique orientation patch and the taught reference-to-grasp relationship. Keep live integration disabled until those are verified. Every output is marked `offline_only: true` and `motion_authorized: false`; no production target files are written.

Sources: [Corning product 353296](https://ecatalog.corning.com/life-sciences/b2b/us/en/Microplates/Assay-Microplates/96-Well-Microplates/Falcon%C2%AE-96-well-Polystyrene-Microplates/p/353296), [Corning dimension drawings, printed pages 15–16](https://www.corning.com/content/dam/corning/catalog/cls/documents/brochures/CLS-DL-CC-016_REV1_DL.pdf), [OpenCV planar homography and pose](https://docs.opencv.org/4.10.0/d9/dab/tutorial_homography.html).
