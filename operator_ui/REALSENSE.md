# RealSense D405 depth view

Open **http://127.0.0.1:5002 → D405 Depth**. The console was reloaded on
2026-10-12; the robot was left disconnected. No arm movement was commanded.

## First camera test

1. Connect the D405 directly to a USB 3 port with a suitable data cable.
2. Close RealSense Viewer / other applications using the D405.
3. Refresh the Flask console, open **D405 Depth**, and select **Start D405**.
4. Check the device name, serial (status API), USB mode, fresh-frame status,
   color image, depth image and 3D cloud. The requested profile is 640×480,
   depth Z16 + color RGB8, at 30 frames/s. This profile passed the first hardware test below.
5. Orbit/pan/zoom the cloud. Display controls set near/far range, RGB/depth
   coloring and point density; **Full** displays all valid points within range.
6. **Save depth + color + cloud** saves a capture. **Release camera** stops
   capture and releases USB ownership before opening the standalone Viewer.

**Sample view (no camera)** is explicitly synthetic and is never represented as
D405 data. Its flat surface is 300 mm away; the circular foreground is 240 mm.
No connection, mode or startup request to this feature commands the robot.

## Installed software

- Isolated Python 3.10 environment: `.venv-realsense/`.
- RealSense Python SDK `pyrealsense2==2.58.1.10581` (stable), Viser 1.1.1,
  MuJoCo 3.15.0; versions pinned in `requirements-realsense.txt`.
- Requested repository cloned to `third_party/mjviser/`, editable installation,
  mjviser 0.0.14, commit `ae0b219a2049a95e1321214e4efd1d395ee4bf39`.
- Official portable Viewer: `tools/realsense/RealSense.Viewer.exe`, version 2.58.1.
  Windows signature validated: RealSense Inc.
  SHA256: `88FF23D7C4CEA83FC8EA674526B7195D3E9D2A1D1C4345E2EF7288696883013E`.
  SDK runtime is supplied by the installed Python wheel; no camera firmware
  changes or system-wide SDK installer was run.

Sources: [mjviser](https://github.com/mujocolab/mjviser),
[RealSense SDK 2.58.1](https://github.com/realsenseai/librealsense/releases/tag/v2.58.1),
[Python point-cloud example](https://github.com/realsenseai/librealsense/blob/master/wrappers/python/examples/opencv_pointcloud_viewer.py).

To recreate the Python environment, run from the project root:

```powershell
./operator_ui/setup_realsense.ps1
```

The setup script clones the recorded mjviser revision if missing. Existing
checkouts are preserved; compare their commit before reproducing this install.
The portable Viewer can be downloaded from the linked official release.

### Linux setup

From the repository root, install the optional worker separately from the core
console. The launcher selects `.venv-realsense/bin/python` on Linux and
`.venv-realsense/Scripts/python.exe` on Windows.

```bash
python3.10 -m venv .venv-realsense
git clone https://github.com/mujocolab/mjviser.git third_party/mjviser
git -C third_party/mjviser checkout ae0b219a2049a95e1321214e4efd1d395ee4bf39
.venv-realsense/bin/python -m pip install -r operator_ui/requirements-realsense.txt
.venv-realsense/bin/python -m pip check
```

If `third_party/mjviser` already exists, inspect its revision instead of cloning
over it. Install the RealSense SDK USB/udev rules appropriate for your Linux
distribution so the camera is accessible without running the console as root.
Use **Sample view** first. The core Windows setup and both launcher path branches
are covered by offline checks; a physical Linux D405 session still needs local
hardware validation. The Windows portable Viewer is optional and not required
by this Python worker.

## Data and coordinate conventions

Point coordinates come from the RealSense SDK's calibrated `pointcloud` function,
including camera distortion. Color is sampled using the SDK's depth-to-color
texture coordinates. Invalid / zero depth is excluded; no hole-filling or
temporal fusion is applied. Color and native depth are not assumed pixel-aligned.

Everything is in the **camera optical frame: X right, Y down, Z forward, meters**.
The center distance is a median of valid depth in a 5×5 center patch, shown in mm.
It is camera-axis depth, not distance from the robot TCP or Euclidean range.
The camera-to-robot transform is **not calibrated**. The mjviser camera marker
is schematic; it is not a collision model or a robot overlay.

Each capture in `operator_ui/realsense_captures/<timestamp>_<id>/` contains:

| File | Contents |
| --- | --- |
| `depth_raw.png` | Native uint16 Z16 depth; multiply by metadata `depth_scale_m` |
| `depth_m.npy` | Full-resolution float32 depth in meters; zero is invalid |
| `color.png` | Native color frame |
| `cloud_m.ply` | All positive finite SDK points with RGB, in meters |
| `metadata.json` | Source, time, scale; real frames additionally include serial, intrinsics, distortion, depth-to-color extrinsics, frame number and device timestamp |

Display decimation/range filtering never changes raw saved depth or full-cloud
exports. A single view contains visible surfaces only, not hidden geometry or a
fused scan of the whole cell. Camera frames do not automatically become robot
collision constraints or Depth Anything training labels.

## Implementation and lifecycle

- `realsense_service.py`: standard-library adapter registered in `app.py`.
  It starts a separate hidden worker using the isolated environment on demand.
- `realsense_worker.py`: one USB owner, cached frames, retry while waiting for
  D405, fresh-frame checks, exports and Viser server. It uses the cloned
  `mjviser.ViserMujocoScene` for the schematic camera marker and the same Viser
  scene for the actual metric point cloud. No robot-service imports.
- `realsense_processing.py`: metric cloud filtering, SDK UV sampling, depth
  colorization and binary PLY output.
- `static/realsense.js`: new console tab, statuses, viewer iframe, controls.
- Local ports: Flask 5002; worker API 5056; Viser 8086 (actual port in status).
  Bound to loopback. Opening the tab starts the viewer but does not open the
  camera. Start explicitly; Release clears frames and closes the pipeline.
- Worker persists across browser refreshes. See `operator_ui/realsense_worker.log`
  for startup issues. Restarting the robot console does not require a second
  depth worker; the adapter reuses a healthy existing worker.

## Validation completed without camera

Seven offline tests passed: invalid-depth rejection, UV bounds, meter-preserving
PLY, missing-D405 recovery/release, stale-frame rejection, synthetic full-resolution
exports, API allowlist, and Viser/mjviser startup (some tests cover multiple cases).
`pip check` passed. A headless Edge test on the updated Flask console verified
tab navigation, the WebGL canvas, synthetic label, image streams, snapshot saving
and release behavior, with zero JavaScript exceptions.
Two additional production-Flask integration tests passed: depth controls remain
independent of robot sequences, and the existing robot motion ownership guard
still rejects motion during an active sequence (nine tests total).

Report and screenshot: `operator_ui/reports/realsense_setup_20261012/`.
## First D405 hardware test - 2026-10-12

- D405 serial 260322279286, firmware 5.15.1.55, USB 3.2 detected.
- Live 640x480 depth + color worked at approximately 30 fps. Six samples over
  five seconds all had fresh frames (age 0.01-0.03 s), with 82.6-84.5% nonzero
  depth. Nonzero depth is coverage, not an accuracy score.
- Flask color/depth images and the Viser WebGL point cloud passed the live
  browser check with zero JavaScript exceptions. Stream left running; no robot
  commands issued. Screenshot/report: `reports/realsense_setup_20261012/` files
  `depth_tab_live.png` and `browser_live_check.json`.
- Reference capture: `realsense_captures/20261012T170234_f9c46cf3/`.
  Native uint16 depth, metric NPY, color, full PLY and calibration metadata saved;
  raw depth multiplied by SDK scale agrees with saved metric depth.
- Scene shows the arm/rack. Center patch reported 1.18-1.25 m, beyond the D405's
  ideal 7-50 cm range. About 25.5% of the saved image had depth in that range.
  This verifies streaming/export; absolute accuracy and MSE remain unmeasured
  until a stationary target at an independently measured distance is tested.

```powershell
& .venv-realsense/Scripts/python.exe -B operator_ui/tests/test_realsense.py
```
