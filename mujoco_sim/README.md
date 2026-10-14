# Offline S4 demonstrations and contact simulation

This is an **approximate physics prototype**, not a calibrated digital twin,
collision-safety certificate, trained policy, or hardware motion executor.
Nothing here connects to the robot. Existing hardware UI actions are unchanged.

## Updated measured layout - 2026-10-12

`open_project.py` now opens the updated layout from `workcell_dimensions.json`.
Edit measurements there; `measured_scene.py` converts inches to millimeters and
computes placement. The previous recorded runs and scripted transfer demos retain
their historical geometry/waypoints; their passing results do not validate this
new layout. The Flask browser's older CAD preview is separate from this MuJoCo scene.

| Measurement | Inches | Millimeters |
| --- | --- | --- |
| Rack overall height | 16 | 406.4 |
| Rack overall width | 4.25 | 107.95 |
| Rack overall depth | 5.5 | 139.7 |
| Each shelf tray and calibration plate | 3.5 x 5.5 | 88.9 x 139.7 |
| Shelf pitch (top to top) | 3.5 | 88.9 |
| Plate gap to left of rack (corrected) | 5.5 | 139.7 |
| Plate gap toward arm | 6 | 152.4 |

Both placement offsets are **nearest-edge gaps** measured along the rack axes.
Looking from the arm toward the rack, the calibration plate's long edge runs
left-to-right. The user corrected the placement to the arm's LEFT: rack-local
-X is left; -Y is toward the arm. Its center is (-263.525, -266.7) mm relative
to the rack. At the retained, unverified rack pose
(580, -120, 0) mm, yaw -90 degrees, its robot-frame center is (313.3, 143.525)
mm and yaw is -90 degrees. These coordinates are a simulation construction,
not a measured robot-frame registration.

The exterior dimensions include the base and posts. Five shelves, first shelf
top at 20 mm, 3 mm shelf thickness, lips/posts, 14.4 mm calibration plate
thickness, 20 mm source support, mass and gripper geometry remain estimates.
With the assumed first height, shelf tops are 20, 108.9, 197.8, 286.7, 375.6 mm.
The existing jaw model opens to 88 mm, smaller than the measured 88.9 mm plate
width; real jaw opening/contact geometry must be measured before replanning a
grasp. No gripping motion or physical movement was tested for this layout.

```powershell
& mujoco_sim/.venv/Scripts/python.exe -B mujoco_sim/open_project.py
& mujoco_sim/.venv/Scripts/python.exe -B mujoco_sim/open_project.py --render --output mujoco_sim/runs/measured_layout_20261012
& mujoco_sim/.venv/Scripts/python.exe -B mujoco_sim/test_measured_scene.py
```

Review images and generated scene/config: `runs/measured_layout_20261012/`.
Three checks passed: exact rack bounding dimensions/pitch, plate orientation
and edge gaps, and two seconds of stable physics with only plate/support contact.
All seven existing contact-simulation regression checks also passed.

## Record in the operator console

1. Refresh the console and open **3D View**. Initialize the colored preview.
2. Set rack position/target shelf and the cyan plate's starting center, support
   height and yaw. These are robot-frame millimeters/degrees, Z up.
3. Click **Start recording**. Drag the colored arm or use target fields/Z controls.
   Accepted pose changes become timestamped keyframes; invalid joint targets do not.
4. Select phases (approach, grasp, lift, insert, release, withdraw) and set simulated
   E1 (0–28 mm). The purple jaws open/close; gap = 60 + E1 mm. These are NOT the
   hardware gripper buttons. Cyan line is TCP motion, not claw-center motion.
5. Stop, then **Export demonstration JSON**. Export before refreshing: the draft is
   held in memory. Starting another recording asks before replacing it.

Rack placement, configuration, joint reference and plate start are captured in the
export. The cyan browser plate stays at its start; it is not artificially attached
to the jaws. Browser motion remains kinematic; contact is evaluated in MuJoCo.
Gripper proxy is attached to the existing CAD wrist, whose registration is still
approximate; MuJoCo uses the project's analytic kinematic frame.

## Replay (PowerShell, from project root)

To open a persistent interactive test cell with the last observed rack placement
(X580, Y−120, Z0, yaw−90 degrees), use:

```powershell
& mujoco_sim/.venv/Scripts/python.exe mujoco_sim/open_project.py
```

The MuJoCo Control panel adjusts simulated actuator targets only: J1 in meters,
J2/J3/J4 in radians, and each finger slider in meters (0.014 each = E1 28 open).
The saved `start_open` keyframe restores the initial pose and plate. This viewer
stays open until you close it; unlike replay, it does not exit after a trajectory.
Generated scene/config are in `mujoco_sim/runs/interactive/`.

```powershell
& mujoco_sim/.venv/Scripts/python.exe mujoco_sim/contact_sim.py "C:/Users/Cephla/Downloads/s4-demo-REPLACE.json" --output mujoco_sim/runs/my-demo --viewer
```

Omit `--viewer` for fast offline evaluation. Use a fresh output folder for each run;
the named report/render/rollout files are overwritten on repeated runs there.
The interactive viewer only controls simulation. Close it to stop replay.

Outputs: `scene.xml`, `final.png`, `report.json`, `rollout.npz`. The report includes
contact pairs, maximum penetration, joint tracking error and final plate pose.
`target_shelf_contact` is only contact evidence, NOT successful placement: release,
plate footprint/orientation, stability and safe withdrawal still need evaluation.
Rollout frame columns: time, model qpos (model.nq), qvel (model.nv), six actuator
targets, reference segment index. Load `scene.xml` to resolve joint addresses;
the free plate's coordinates precede the arm's. Units are meters/radians/seconds.

Reference actions are J1/J2/J3/J4 and two symmetric finger positions. GUI E1 is
converted to half-gap increment. Each segment is quintic, stopping at keyframes,
retimed to conservative reference velocity/acceleration bounds. Mouse timestamps
are retained in JSON but not used as robot timing; stationary phase changes get a
minimum 0.25 s dwell. This is not yet controller-latency identification or a
continuous optimized trajectory. Very dense recordings may replay slowly.

## Model and limitations

- Analytic 200 mm links and (126,0) mm base from project configuration. J1 slide,
  J2/J3/J4 hinges; finite control force, position servos, gravity and joint stops.
- Plate is a free rigid body; no weld, teleport, or automatic successful grasp.
  Two sliding jaws hold it only through frictional contact. Estimated box jaws,
  not an exact model of the real comb plates. E2 rotation is not modeled.
- Independent box shelves (not a convex hull of the entire rack), rear lips,
  posts, base, pedestal, floor and primitive arm/tool collision shapes.
  Solid shelf proxies intentionally omit holes/notches, conservatively blocking
  those areas. Adjacent linked bodies use MuJoCo's default collision filtering.
- User measured rack dimensions are preserved. Shelf count/first height, arm
  cross-sections/vertical offsets, gripper shape, plate dimensions/mass, fixture
  pose, friction, servo gains/forces and masses remain estimates. No physical
  deployment should rely on this model before measurement and commissioning.
- Initial penetration greater than 1 mm is rejected. Later collisions are
  physically resolved and reported, not silently bypassed. MuJoCo contacts and
  stops have finite compliance; neither they nor the browser guarantee clearance.
- No RL training, hardware bridge, ArUco dependency or external trajectory upload.

## Verification

### Placement from the measured current arm pose

`current_pose_demo.py` reads a saved controller snapshot without connecting to
hardware. It initializes J1-J4 exactly from that snapshot and sets the model's
Z and wrist offsets from the measured TCP. The virtual plate starts between
the jaws, with a simulated contact aperture; physical E1 was not measured.
There is no left-side pickup pedestal, attachment weld, or plate teleport.

```powershell
& mujoco_sim/.venv/Scripts/python.exe -B mujoco_sim/current_pose_demo.py --snapshot mujoco_sim/current_pose_snapshot_20261009.json --output mujoco_sim/runs/current_pose_replay --viewer
```

The 2026-10-09 trial matched the initial measured TCP to 0.00053 mm in the
analytic model. The plate starts at approximately (479.054, 55.174, 265.833) mm,
with yaw 10.153 degrees. The reference Z offset is 38.599 mm. The sequence lifts,
rotates at clearance height, approaches outside the rack, lowers outside it,
inserts onto shelf 2, releases and withdraws. All 11 reference phases passed the
existing shared path guard with the unchanged physical workspace envelope.
The 72.116-second headless physics run passed release, support, upright,
footprint and settled-velocity checks, with no unwanted contacts.

The rack remains at the previous assumed simulation position (580,-120,0),
yaw -90 degrees. Matching the initial TCP does not verify the physical shelf's
height, collision geometry or tool contact geometry. No hardware motion was run.

**Subsequent hardware rehearsal, 2026-10-09:** After the operator confirmed the
empty jaws, clear swept area, E-stop supervision, and verified rack entry/release
poses and connecting path, `operator_ui/hotel_rehearsal.py` attempted the same
TCP route with the physical envelope enabled. Nineteen segment arrivals passed;
the controller reported axis-4 collision fault 3873 during segment 20 of the
high-level approach, at about TCP (275.798,-26.959,329.992), before rack descent
or insertion. Servos disabled; program was stopped and the remaining steps
cancelled. No error clearing or motion retry. Cause is not established by the
simulation. Details: `operator_ui/reports/hotel_rehearsal_20261009_live/`.
Execution used the deterministic Flask controller interface, not Haiku.

This variant saves `source_snapshot.json`, `scene_config.json`, `waypoints.json`,
`initial.png`, `final.png`, `scene.xml`, `report.json` and `rollout.npz`.
Its rollout contains named columns: time, qpos, qvel, six commanded actuator
targets, TCP XYZ and plate XYZ, plus a phase array, sampled at 20 Hz in SI units.
Unlike the older demo, it writes the final report as soon as the trajectory
finishes, while the viewer remains open. R restarts; P pauses/resumes. Restart
clears the previous run's counters and restores its initial physics state.

### Scripted plate-to-rack demonstration

The current-pose simulator accepts `--entry-retreat-mm 10` to test an approach
10 mm farther from the rack along -X (opposite this scene's +X insertion).
It retreats before lateral travel and shifts outside staging and withdrawal;
the placement target stays fixed. Example results are in
`runs/entry_retreat_10mm_20261009`. This is an offline candidate only: the real
collision has not been reproduced by the primitive model. See `Observations.md`.

```powershell
& mujoco_sim/.venv/Scripts/python.exe mujoco_sim/pick_place_demo.py --viewer
```

This approximately one-minute physics test picks the plate at (350, -180),
places it on shelf 2 at (580, -120), and withdraws. R restarts and P toggles
pause. The viewer holds the final state until closed. Omit `--viewer` for the
fast headless test; results are saved to `runs/pick_place` (viewer results are
written when its window closes). This is a hand-scripted reference, not RL.

The jaws grip the plate's upper sidewalls to clear the source pedestal, then
release approximately 9 mm above the shelf to clear their lower edges. There
is no grasp attachment/weld. Elliptic friction and MuJoCo's no-slip solver
iterations reduce numerical drift; real friction/force limits remain unmeasured.
The successful offline trial checked lift, shelf contact, released jaws, settled
velocity, upright orientation, footprint containment, and no unwanted contacts.

```powershell
& mujoco_sim/.venv/Scripts/python.exe mujoco_sim/test_contact_sim.py
```

Tests cover FK, jaw aperture, reference rejection, retiming, free plate settling
on a shelf, friction-only grasp/lift/release, initial penetration rejection, and
full replay/report/render output. These component tests do not establish an
end-to-end successful plate transfer to the rack.
