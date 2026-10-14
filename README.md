# Bioyond S4 — progress and setup

Software for calibrating the two-disk plate, viewing camera depth, and testing
the workcell in MuJoCo.

## Progress so far

| Feature | Status |
| --- | --- |
| **Faster calibration — plate only** | Implemented and tested on the two-disk calibration plate. Continues until confirmed convergence, operator stop, or fault. This does not complete alignment or pickup. |
| **IC alignment** | Inverse-compositional Lucas–Kanade matching is implemented. Correctly aligned reference images and live validation are still pending; it currently provides a comparison preview. |
| **MuJoCo** | Updated rack/shelf dimensions and calibration plate placement, now **left of the arm**. The interactive scene works; absolute rack position and tool details remain estimates. Older motion demos use the previous layout. |
| **D405 depth** | Live color, depth, and Viser 3D point cloud tested at 640 × 480, about 30 fps. Camera-to-arm calibration is pending. |
| **Depth Anything V2 / Haiku** | Depth inference and scene-analysis tools are available. Metric-depth training needs reference labels; autonomous picking is not validated. |

## Get the project

Install **Git and 64-bit Python 3.10**. Sign in to GitHub with access to this
private repository, then run:

```sh
git clone https://github.com/BekG123/Bioyond_Cephla.git
cd Bioyond_Cephla
```

Run the commands below from this folder. Windows is the tested hardware setup;
the Linux instructions are a starting point and have not been tested on this cell.

## Windows (PowerShell)

Install and start the Flask console:

```powershell
py -3.10 -m venv .venv
.venv/Scripts/python.exe -m pip install flask numpy opencv-python
.venv/Scripts/python.exe operator_ui/app.py
```

Open **http://127.0.0.1:5002**. For the GigE camera and plate calibration, install
the HIKROBOT MVS SDK, including its Python bindings. Close other camera viewers
before using it here.

To open MuJoCo, use another terminal:

```powershell
py -3.10 -m venv mujoco_sim/.venv
mujoco_sim/.venv/Scripts/python.exe -m pip install -r mujoco_sim/requirements.txt
mujoco_sim/.venv/Scripts/python.exe mujoco_sim/open_project.py
```

For the D405, run `./operator_ui/setup_realsense.ps1` once. Connect the camera
to the computer's USB 3 port, then select **D405 Depth → Start D405** in Flask.

## Linux (Ubuntu 22.04 desktop)

Use Python 3.10. A desktop/OpenGL driver is needed for the MuJoCo window.
On other distributions, install the equivalent packages for your system.

```bash
sudo apt update
sudo apt install git python3.10-venv libgl1 libglib2.0-0 libglfw3
python3.10 -m venv .venv
.venv/bin/python -m pip install flask numpy opencv-python
.venv/bin/python operator_ui/app.py
```

Open **http://127.0.0.1:5002**. For MuJoCo, in another terminal:

```bash
python3.10 -m venv mujoco_sim/.venv
mujoco_sim/.venv/bin/python -m pip install -r mujoco_sim/requirements.txt
mujoco_sim/.venv/bin/python mujoco_sim/open_project.py
```

For D405, first follow the [official RealSense Linux setup](https://github.com/realsenseai/librealsense/blob/master/doc/distribution_linux.md)
for your Ubuntu/kernel version, including USB permissions. Then:

```bash
git clone https://github.com/mujocolab/mjviser.git third_party/mjviser
git -C third_party/mjviser checkout ae0b219a2049a95e1321214e4efd1d395ee4bf39
python3.10 -m venv .venv-realsense
.venv-realsense/bin/python -m pip install -r operator_ui/requirements-realsense.txt
.venv-realsense/bin/python operator_ui/realsense_worker.py
```

Keep that terminal running alongside Flask, then select **D405 Depth → Start D405**.
Manual worker startup is needed because Flask's current worker launcher uses a
Windows Python path. For GigE capture on Linux, install the vendor's Linux MVS
SDK and set `BIOYOND_MVIMPORT` to the folder containing `MvCameraControl_class.py`.
Linux camera/robot hardware operation still needs validation.

## Where to look next

- [Calibration observations](Pick%20and%20Hold/Calibration/Observations.md) — live results and changes.
- [IC alignment](Pick%20and%20Hold/Align/README.md) — capture the reference images needed next.
- [MuJoCo](mujoco_sim/README.md) — simulation instructions; edit [workcell dimensions](mujoco_sim/workcell_dimensions.json).
- [D405 / Viser](operator_ui/REALSENSE.md) — depth viewing and saved captures.
- [Depth Anything / Haiku](operator_ui/DEPTH_TRAINING.md) — optional model setup and training workflow.

Model weights, Python environments, and captured datasets are not included in
Git. MuJoCo runs offline. For physical motion, use the commissioned controller
program, verified workspace, and supervised E-stop; only one application may
own the robot connection at a time.
