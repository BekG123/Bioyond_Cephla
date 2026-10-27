# Bioyond S4 — progress and setup

Software for calibrating the two-disk plate, viewing camera depth, and testing
the workcell in MuJoCo.

## Progress so far

The default page at **http://127.0.0.1:5002** is the **Cephla researcher workspace**:
**Prepare → Teach → Run**. Start with **Home → Hamilton**: connect the robot,
start a teaching draft, capture **Home**, run **plate calibration**, then **Align**,
record your manually performed **Descend** and **Grip**, then capture **Hamilton**.
Intermediate route points can be captured after Grip. Review and save; drafts
survive page reloads. Existing Home-only drafts can adopt this workflow.
After placing the plate in view, release the arm, confirm readiness and click
**Calibrate**. It exits DragGo and runs automatic corrections with **Wide** fixed,
showing errors and completed corrections. It uses the existing convergence math,
has no workspace-envelope activation prompt, and saves each attempt's log.
Align remains a separate automatic action with its existing checks. Manual record buttons read
arm/gripper positions; they do not execute the actions or verify a secure grasp.
The full Home → Hamilton → Home → Octopi routine comes later.

Both views automatically log JSON requests/responses, robot status (including E1),
and sequence progress under `operator_ui/logs/audit/`. Developer view provides
**Download audit JSON** and **Log status**. Credentials and binary images are omitted;
the logs are evidence for review, not an executable teaching routine.

This captures **individual station positions**, not continuous hand-guided
motion. Teach now has direct **Start / End hand-guiding (DragGo)** controls;
Bioyond Works is not needed. See [hand-guiding instructions](operator_ui/DRAGGO.md).
Researcher **Run** now has separate **Descend** and **Grip** buttons backed by
Haiku and a **Stop** button. Add the API key and review measured pickup references
in Developer view. Haiku uses selected log summaries as context; it does not train
model weights. The earlier collision-session export is diagnostic evidence and
cannot supply its missing descent/E1 targets. Hardware validation is pending.
Enter the Haiku key once: Windows saves it encrypted for your user account and
restores it after restarts. Linux needs `keyring` with an unlocked Secret Service,
or the `ANTHROPIC_API_KEY` environment variable.
Full routine playback and Pause remain unavailable. Connecting and capturing
never enable or move the arm.

The existing technical console is at **http://127.0.0.1:5002/developer**.
Calibration, coordinates, torque, model settings, camera/depth tools, and logs
remain there. These are separate views, not separate authenticated user roles.
See [researcher UI developer notes](operator_ui/RESEARCHER_UI.md).

| Feature | Status |
| --- | --- |
| **Faster calibration — plate only** | Implemented and tested on the two-disk calibration plate. Continues until confirmed convergence, operator stop, or fault. This does not complete alignment or pickup. |
| **IC alignment** | Inverse-compositional Lucas–Kanade matching is implemented. Correctly aligned reference images and live validation are still pending; it currently provides a comparison preview. |
| **MuJoCo** | Updated rack/shelf dimensions and calibration plate placement, now **left of the arm**. The interactive scene works; absolute rack position and tool details remain estimates. Older motion demos use the previous layout. |
| **D405 depth** | Live color, depth, and Viser 3D point cloud tested at 640 × 480, about 30 fps. Camera-to-arm calibration is pending. |
| **Depth Anything V2 / Haiku** | Depth inference and scene-analysis tools are available. Metric-depth training needs reference labels; autonomous picking is not validated. |

## Bioyond Works setup (Windows)

This is Bioyond's own robot-control application, separate from our Flask console.
The vendor manual specifies **Windows 10 or newer**; use a Windows PC for this
step even if you run our Python tools on Linux.

1. **Download** `BioyondWorks_Robot.exe` using the installer link supplied with
   the robot. If you need the link, request it from [Bioyond](https://www.bioyond.com/en/about-us).
2. **Install** and follow the prompts. Choose **Reinstall** only for a fresh
   installation; choose **Upgrade** for an existing setup, since Reinstall clears
   its saved user data. Allow network access if Windows prompts.
3. **Log in** by opening **Bioyond Works-S**. The manual's factory login is
   `admin` / `Admin@123`; use your current credentials if these were changed.
   Change the factory password after first login.
4. **Connect** the powered robot and PC by Ethernet. Put the PC on the same
   subnet with a different, unused IP address. In **Module → network
   configuration**, enter the controller's actual IP. This project's controller
   is configured as `192.168.201.220`; the manual's factory example is
   `192.168.3.200`.
5. **Check** that the status bar shows an online connection. This finishes basic
   software setup; it does not require running a robot motion program.
6. **Disconnect Bioyond Works** before connecting through our Flask console;
   only one application can own the robot connection at a time.

Details: [Bioyond Works manual, Quick Start](Bioyond_S4_Agent_Context_Pack/04_Manuals/Bioyond%20Works%20Software%20Manual.pdf),
printed pages 5–7. The installer is supplied separately, not stored in this repo.

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
.venv/Scripts/python.exe -m pip install flask numpy opencv-python PyYAML
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
to the computer's USB 3 port, then select **Developer view → D405 Depth → Start D405**.

## Linux (Ubuntu 22.04 desktop)

Use Python 3.10. A desktop/OpenGL driver is needed for the MuJoCo window.
On other distributions, install the equivalent packages for your system.

```bash
sudo apt update
sudo apt install git python3.10-venv libgl1 libglib2.0-0 libglfw3
python3.10 -m venv .venv
.venv/bin/python -m pip install flask numpy opencv-python PyYAML
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

- [Developer pickup corrections and taught Hamilton buttons](operator_ui/COACTIVE_PICKUP.md) — hand-demonstrated preferences for Descend/Grip; latest tested route in both views.
- [Calibration observations](Pick%20and%20Hold/Calibration/Observations.md) — live results and changes.
- [IC alignment](Pick%20and%20Hold/Align/README.md) — capture the reference images needed next.
- [MuJoCo](mujoco_sim/README.md) — simulation instructions; edit [workcell dimensions](mujoco_sim/workcell_dimensions.json).
- [D405 / Viser](operator_ui/REALSENSE.md) — depth viewing and saved captures.
- [Depth Anything / Haiku](operator_ui/DEPTH_TRAINING.md) — optional model setup and training workflow.

Model weights, Python environments, and captured datasets are not included in
Git. MuJoCo runs offline. For physical motion, use the commissioned controller
program, verified workspace, and supervised E-stop; only one application may
own the robot connection at a time.
