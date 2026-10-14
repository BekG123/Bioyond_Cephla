# Train Depth Anything V2 Small on Flask camera captures

**Start here: images alone are not metric-depth training labels.** The downloaded
24.8M-parameter model already estimates relative scene depth without training.
Fine-tuning it to your cell requires independently measured, registered depth.
Neither Haiku nor the model's own predictions provide ground truth.

The runtime is **camera only**: original image -> local Depth Anything -> Haiku
scene description. Haiku has no Calibrate, Align, Descend or Grip tools. The
separate manual robot console remains available. No scene request moves the
robot or changes intrinsics, hand-eye calibration, workspace limits or grip Z.

## 1. Capture through Flask

Start the console from the repository root with the GPU environment:

```powershell
.venv-depth/Scripts/python.exe operator_ui/app.py
```

In **Scene camera agent**, choose a capture session such as `train_day1` and click
**Save training capture**. Use **Local depth** to also compute a depth map without
an API key. **Analyze with Haiku** sends the camera image, depth visualization
and coordinates to Anthropic; it requires the existing API key. All three modes
save the original lossless PNG locally. JPEG compression is only for the API;
it does not turn images into fewer visual tokens via custom Huffman encoding.

Capture varied plate placements, lighting, backgrounds and camera viewpoints
within the independently verified workspace. Operate the robot manually; this
pipeline does not move it for data collection. Keep the scene still during
capture. Collect separate physical setups/sessions for train, validation and
test, rather than putting adjacent nearly identical frames in different splits.

Each capture creates:

```text
operator_ui/datasets/depth/<session>/<timestamp_id>/
  rgb.png             original camera image
  metadata.json       timestamps, camera details, before/after robot pose,
                      current calibration snapshot and label provenance
  prediction.npy      optional raw model output; NOT a training label
  depth_preview.png   optional per-image normalized visualization
  haiku.json          optional description and API token usage
```

Before/after robot poses are best-effort metadata, not hardware-synchronized
camera poses. Relative outputs have arbitrary scale/shift and cannot establish
millimeters or collision clearance. Color scales differ between captures.

## 2. Attach measured depth to each training image

Create an **HxW float32 NumPy array in meters**, matching `rgb.png` pixel for
pixel. Values must be optical-axis camera Z, not robot Z or Euclidean ray range.
Use `0` or `NaN` for unknown/invalid pixels. Obtain labels with registered RGB-D,
calibrated stereo, or an independently measured plane and calibrated intrinsics.
For a tilted plane, compute ray-plane intersections; a constant depth label is
valid only for a plane parallel to the image plane. Mask everything off that
measured plane. A marker size, one robot pose or one measured distance is not a
dense scene label. Existing camera intrinsics/hand-eye calibration require their
own geometric calibration procedure; Depth Anything does not replace it.

For example, after exporting a measured depth array to `labels/frame001_m.npy`:

```powershell
.venv-depth/Scripts/python.exe operator_ui/depth_dataset.py label --sample "operator_ui/datasets/depth/train_day1/<timestamp_id>" --depth "labels/frame001_m.npy" --source rgbd_registered
```

Replace `<timestamp_id>` with the actual saved folder. Other source choices are
`calibrated_stereo` and `measured_plane`. The helper checks shape/type/valid
pixels, stores `depth_m.npy`, and records its source and hash. It rejects the
pipeline's `prediction.npy` as a label. Do not relabel model predictions as
measurements: that would teach the model its own errors.

## 3. Split entire sessions and validate the pairs

After labeling captures in `train_day1`, `validation_day2` and `test_day3`:

```powershell
.venv-depth/Scripts/python.exe operator_ui/depth_dataset.py prepare --val-session validation_day2 --test-session test_day3
.venv-depth/Scripts/python.exe operator_ui/train_depth.py --train operator_ui/datasets/depth/manifests/train.jsonl --val operator_ui/datasets/depth/manifests/val.jsonl --check-only
```

Unlabeled captures are skipped. The command refuses empty splits and overlapping
validation/test sessions. Reserve test scenes until after model selection. These
session names are examples; choose representative, separately captured scenes.

## 4. Fine-tune the Small model

```powershell
.venv-depth/Scripts/python.exe operator_ui/train_depth.py --train operator_ui/datasets/depth/manifests/train.jsonl --val operator_ui/datasets/depth/manifests/val.jsonl --output operator_ui/depth_runs/small_metric_run1 --epochs 20 --max-depth 2
```

This Windows-compatible, single-GPU trainer uses the official Small architecture
and pretrained encoder, initializes a metric DPT head, and optimizes a masked
log-depth loss. It freezes the encoder by default, uses batch size 1 with aspect
ratio preserved, and trains at a 518-pixel short side. `--max-depth 2` means a
2-meter output range; adjust to the measured dataset's range. With sufficient
varied labels, `--unfreeze-encoder` allows encoder fine-tuning at one tenth of
the head learning rate. On memory pressure, try `--image-size 392` (multiple of
14). Choose a new output directory for each run.

The checkpoint with the best validation MAE is saved as `best.pt`; epoch loss,
MAE, RMSE and absolute relative error are logged in `history.jsonl`. This is a
local adaptation of upstream metric training, not a reproduction of the original
large-scale V2 pretraining recipe. It has no Flask or robot imports.

## 5. Evaluate and explicitly select a trained checkpoint

```powershell
.venv-depth/Scripts/python.exe operator_ui/train_depth.py --evaluate operator_ui/datasets/depth/manifests/test.jsonl --checkpoint operator_ui/depth_runs/small_metric_run1/best.pt
```

Evaluate errors separately on plate edges, reflective areas and the closest
surfaces, across all intended lighting/poses. Report task-specific worst-case
errors as well as the script's mean metrics. Low average error alone does not
establish safe robot clearance. Use an independent geometric reference for
validation; do not treat a training fit as camera calibration.

After validation, stop the idle Flask server and start it with:

```powershell
$env:BIOYOND_DEPTH_CHECKPOINT = (Resolve-Path operator_ui/depth_runs/small_metric_run1/best.pt).Path
.venv-depth/Scripts/python.exe operator_ui/app.py
```

The UI will label outputs as **estimated metric depth**. This still grants no
robot motion authority. To return to the relative model, remove that environment
variable before restarting. API keys entered through the panel must be entered
again after a server restart.

## Source, setup and license

Official source: https://github.com/DepthAnything/Depth-Anything-V2

Pinned commit: `a561b849ebae10a6f5ef49e26c83cbbcd36c71bf`.
Small checkpoint: `models/depth_anything_v2/depth_anything_v2_vits.pth`.
Downloaded SHA256: `715fade13be8f229f8a70cc02066f656f2423a59effd0579197bbf57860e1378`.
Small uses Apache-2.0; see the checkout's LICENSE. Upstream metric training:
`third_party/Depth-Anything-V2/metric_depth/train.py`.

To reproduce this installation: `& ./operator_ui/setup_depth.ps1` in PowerShell.
PyTorch 2.7.1 / torchvision 0.22.1 CUDA 12.6 are pinned for this machine's driver.
The environment inherits the existing Flask/OpenCV camera dependencies; no
global Python packages are replaced. Source checkout, weights, environments,
datasets and training outputs are excluded from the parent repository's Git.

Tests: `py -B -m unittest discover -s operator_ui/tests -p test_plate_agent.py -v`.
The existing camera frame has been used for an inference smoke test; no measured
training labels have been collected or trained on by this change.
