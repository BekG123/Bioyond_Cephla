# Depth collection status — 2026-09-18 PDT

The requested **25-view sweep is complete**, with four additional return
captures. Fine-tuning has not started because independent depth labels are
still unavailable. Do not automatically resume any ledger in an `error` state.

## Preserved pretrained baseline

`depth_baselines/pretrained_20260918T232447/` contains the original `rgb.png`,
raw `prediction.npy`, `depth_preview.png`, and `metadata.json`. `baseline.json`
records SHA-256 hashes verified against the source sample, plus the model
checkpoint hash and inference settings. These predictions are relative inverse
depth, not measurements or training labels. Keep this image out of training for
a later same-image visual comparison; a numerical accuracy comparison still
requires independent reference depth and a documented scale treatment.

## Physical state and acquisition

The user confirmed E-stop supervision, an empty gripper, clear travel, and nearby
XY-only collection with fixed height/wrist angle. Read-only inspection found
X303.289, Y20.513, Z286.304 mm, Rz9.940 degrees, manual mode, enabled, paused,
and no controller errors. The visible target is the two-circle vendor plate,
not an ArUco marker. The vendor circle detector recognized both circles and its
camera-math self-test passed.

`collect_depth_views.py` plans 25 unique views on a 2 mm grid within +/-4 mm
in X and Y, followed by four return steps. Each step checks the existing
workspace envelope and full joint path. Every image records before/after pose
and validates circle visibility, size and orientation. This is one acquisition
session, not an independent train/validation/test split.

The robot was switched to Auto and the paused program was safely stopped/started.
Program startup reset the confirmed-empty gripper to approximately E1=0.011.

- First attempt, `datasets/depth/plate_xy_20260918/`: saved one stationary image;
  stopped before XY motion after a J4 deviation from a single-reading baseline.
- Second attempt, `datasets/depth/plate_xy_20260918_v2/`: used five stationary
  torque samples and the existing operator-configured 66-count band. Saved the
  starting image, moved X by +2 mm at speed 5, verified arrival and fixed Z/Rz,
  and saved the second image. Both circles remained visible. Then stopped when
  J3 changed from -29 to 46 and J4 from 7 to -142 counts. The original baseline,
  latest torque and post-stop state are in `collection.json`.
- Five stationary follow-up readings showed J4 between -99 and -127 counts;
  the deviation persisted. No further movement or return-to-origin was issued.

Pose at the pilot pause: **X305.290, Y20.513, Z286.304 mm, Rz9.940 degrees**.
Controller: Auto, enabled, program running but arm stationary, no reported errors.
The script disconnected its TCP client and released the camera.

Pilot images:
- `datasets/depth/plate_xy_20260918_v2/20260919T000014_91c939227d/`
- `datasets/depth/plate_xy_20260918_v2/20260919T000016_7bbd9e2db9/`

The second image is saved even though its post-capture torque check failed;
it is not included as a successful sample in the ledger's `samples` list.

## Remaining work

1. Obtain independently measured/registered camera-Z depth or a verified plate
   plane and intrinsics. Known robot poses, relative predictions and the vendor
   circle-radius heuristic alone are not yet validated dense depth labels.
2. Collect independent
   validation/test setups rather than treating nearby frames as independent tests.
3. Train and evaluate only after labels and splits exist. No camera-specific
   training, MSE, MAE or RMSE result has been produced in this session.

## Completed after operator inspection

The user explicitly reported that the arm was safe and there was no tension,
and instructed continuation. The collector now permits an explicit
`--resume-after-inspection` only for a torque-only pause with a recorded,
fault-free arrival and an image at the commanded endpoint. Dry-run checks and
negative tests rejected unknown motion state and mismatched poses.

The 66-count setting belongs to the existing **Z-descent** guard; applying it as
a cross-pose XY torque threshold was an unvalidated addition in the collector.
The continued sweep used the established `GuardedService` XY path, controller
error/collision, telemetry and arrival checks plus per-view circle tracking.
Torque was logged throughout. Controller protection, limits and the Z-descent
guard were not modified. The operator inspection, prior baseline and readings
are preserved in the ledger's `inspection_recoveries`.

All 29 scheduled images were captured: 25 unique grid points (+/-4 mm, 2 mm
spacing) plus four return repetitions. Both circles were found in every accepted
image. Final verified pose: **X303.289, Y20.513, Z286.304 mm, Rz9.940 degrees**,
matching the original location. Height and wrist angle remained fixed. The
robot client disconnected and the camera was released. The controller remains
Auto/enabled/program running, with the arm stationary.

Session: `datasets/depth/plate_xy_20260918_v2/collection.json`.
Pretrained per-view predictions and hashes are saved by `baseline_depth_session.py`
to `pretrained_baseline.json`; `capture_depth_overview.jpg` shows five example
image/depth pairs. The extra pilot image remains on disk but is excluded from
the 29 accepted records. All frames belong to one physical setup/session.
