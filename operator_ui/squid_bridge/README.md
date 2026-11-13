# Squid settings add-on for Lacry

This optional launcher leaves shipped Squid files unchanged. It adds three local
commands to read selected acquisition settings, start them after checking their
checksum, and cancel only the matching imaging job. Python Exec stays disabled. Starting Squid normally
omits the add-on.

When back at the station, save or note the desired Squid selections, close Squid
normally, and launch with **Squid's own Python environment**:

```powershell
& 'C:/Users/Cephla/AppData/Local/Programs/Python/Python310/python.exe' `
  'C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla/operator_ui/squid_bridge/launch.py' `
  --software 'C:/Users/Cephla/Desktop/squid-latest/software' `
  --simulation --start-server
```

On Linux the command is the same with Linux paths and the Squid environment's
`python`. Do not launch a second Squid instance or point it at hardware during
offline tests. Reload the idle Lacry backend, select the acquisition tab/settings
in Squid, then **Connect to Squid** in Lacry.

### Desktop installation and the existing mock-image cycle workflow

The active installation is now `C:/Users/Cephla/Desktop/squid-latest/software`.
The old Temp copy is not used. `launch.py` defaults to the current user's
`Desktop/squid-latest/software`; `--software` or `SQUID_SOFTWARE_DIR` can select
another installation explicitly. Missing installations fail without fallback.
Use `--check` to print the resolved paths without importing Squid or starting it.

For this cell's established physical-XYZ/simulated-camera cycle workflow, run
`operator_ui/reports/restart_squid_lifecycle.ps1 -PreviewOnly` to inspect the launch.
After saving the current imaging settings and closing Squid normally, an operator
must confirm the stage is empty/clear for startup homing and the arm is at Home.
Then run the script with `-StageClearAndArmHome`. It uses the Desktop installation,
controller 12769210, the existing settings/stage/completion bridge, and the
Windows status-file fix. It refuses a second Squid process even if MCP is off.

In Researcher view, use the existing **Connect to Squid** control, select the
imaging sites/settings in Squid, and request the normal repeated Squid workflow.
No new robot trajectory, loading coordinate, imaging selection or automatic run
is created by this installation change. Existing selections are checked against
the new process session before use. The read-only `get_stage_reference` response
now includes `software_directory` so deployment can be verified. These mock-image
cycles exercise real stage motion, not optical acquisition from a real camera.

Ask: “Fully calibrate, leave the plate at Squid, image using its selected settings,
then retrieve the plate to Home when imaging finishes.” Or choose **Calibrate,
image & retrieve**. Review the complete plan and reply **Yes** once. The workflow
reserves the arm while waiting at Home and does not ask for another routine Yes.
Stop cancels further steps and requests cancellation of its own active imaging
job; an arm movement already in progress finishes first. Faults or uncertain
results stop the workflow without retries or automatic fault resets.

Logs and the confirmed settings snapshot are stored under
`operator_ui/reports/autonomous_squid/<run>/`. Completion must match this run's
experiment ID and run ID. An old completed job or idle state cannot trigger pickup.
The microscope must be back at the confirmed loading position before retrieval.
Squid's native acquisition returns its stage to its starting position; Lacry checks
the feedback afterward rather than assuming it happened.

The default profile in `../squid_protocols.json` currently requires **simulation**.
Real microscopy needs a reviewed loading position and explicit real profile;
configure reviewed microscope return waypoints only if the native return is
insufficient. Robot movement is still real when a live Lacry plan is confirmed,
even with mock imaging. No full physical experiment has been validated by these
offline tests.

The export rejects fitted focus maps and per-region focus offsets instead of
silently dropping them. Selected wells, channels (including exposure/intensity),
Z stack and time points are captured. Changes before imaging require a fresh plan.
Settings are read on the Qt GUI thread; no acquisition starts during planning.

### Physical stage test without the main camera

Launch the same add-on with `--simulate-camera --start-server` in place of
`--simulation --start-server`. This runs the physical controller and stage with
synthetic main-camera images, using Squid's existing per-component simulation
support. It does not change the shipped Squid files. Confirm the controller
serial matches the configuration and the stage is clear for startup homing first.
Other configured peripherals are still physical; this option is not a fallback
for missing controllers or other hardware.
An operator-confirmed controller can be selected for one session using
`--controller-serial SERIAL`. The launcher requires exactly one attached device
with that serial and leaves the shipped configuration unchanged.

For an XYZ-only setup with no filter wheel or optical peripherals, add
`--stage-only`. This selects a synthetic main camera and excludes the absent
filter wheel, laser autofocus, objective changer, external illumination and
fluidics in this session. It retains physical XYZ homing, limits and the native
controller watchdog. These device flags are set before Squid caches its
configuration. Use this mode only after the operator identifies the hardware as
an XYZ-only setup; do not use it to bypass a fault on an installed peripheral.

Lacry reports this as a real-stage test with simulated images, never completed
real microscopy. Before delivery, configure a dedicated profile with
`simulation: true`, `stage_simulated: false`, and the physically reviewed
`loading_position` in microscope coordinates. Do not reuse the simulator's pose.

`plan_squid_experiment(retrieve=false)` performs calibration/pickup, delivery,
return Home, and imaging completion verification, leaving the plate at Squid.
Use `retrieve=true` only when the requested experiment includes retrieval.

Lacry's `get_squid_stage` reads live XYZ and the saved drop-off from
`operator_ui/squid_stage_reference.json`. `plan_squid_stage` proposes either
`dropoff` or native microscope `home`; `after_scan=true` binds a deferred return
to the exact active acquisition. One chat confirmation authorizes that plan.
The robot must remain at Home. Stop cancels pending steps after the native move
in progress finishes; it does not abort an independently started scan.

The external `stage_position.py` add-on delegates loading to Squid's native
objective-retraction and clamp-clearance routine with the operator-taught XY,
restores scanning limits even on failure, then returns to the taught Z.
No shipped Squid source is edited. Reports are in `operator_ui/reports/squid_stage`.
The first 2026-10-23 live trial failed at the final negative-X target: native
loading changes virtual scanning limits but not the firmware's homed range.
The operator approved X +0.050 mm (0.10000625 mm inward); the retry succeeded at
X0.05000625/Y0.05476875/Z1.05 mm. The original target and failed trial remain saved.
Host validation now rejects negative XY on controller 12769210 before motion;
the add-on has the same check for its next launch. The robot did not move.
The operator subsequently accepted the corrected loading placement, and its
review hold is cleared in the active imaging profile. Lacry uses the physical
controller and live stage feedback for positioning. Only camera images remain
simulated in this XYZ-only hardware session; successful stage travel does not
demonstrate optical imaging.

### Scan entry and cleanup lifecycle

`imaging_lifecycle.py` is installed by the launcher after the settings and stage
add-ons. Before a confirmed acquisition, `prepare_confirmed_imaging` verifies the
saved YAML checksum and all selected field coordinates against native scanning
limits, performs Squid's native loading-to-scanning transition, then reaches the
first saved imaging site. The arm must be Home. Acquisition starts there, so its
native post-scan return target is inside scanning limits instead of loading XY.

The add-on wraps the controller's existing acquisition/cleanup methods in memory.
`get_acquisition_status.cleanup` remains pending/running until the native cleanup
callback returns and stage feedback matches the acquisition start. Exceptions or
position errors latch a failure; there are no automatic resets or retries. The
host requires this lifecycle capability for physical automatic experiments and
will not treat finished image files alone as successful cleanup. Shipped Squid
files and stage limits are unchanged. Loading the new add-on requires a normal
Squid restart, whose physical-stage homing needs operator clearance confirmation.

Offline checks: run `test_imaging_lifecycle.py`, `test_stage_position.py` and
`test_bridge.py` with Squid's Python from its software directory. All hardware in
these tests is fake; they do not establish live stage-return success.

`get_current_acquisition_controls` uses the same Qt-thread native serializer as
`get_current_acquisition_settings`, but permits zero fields and starts no work.
This lets the host read current time, channel and Z controls at loading instead
of substituting an entire old acquisition. `selection_snapshot.recover_xy`
restores only compatible Current Position XY locations. It checks tab, objective,
plate and scan layout; it never changes the live GUI or uses old per-field Z.
The host checks the merged snapshot again at confirmation. No change to shipped
Squid source, Python Exec, or Lacry's prompt is needed.
# Windows acquisition status files

The launcher installs `state_io.py` in memory before loading Squid. Its native
acquisition writer uses replacement-compatible Windows I/O and retries only
WinError 5/32/33 for at most 0.7 seconds total delay. Lacry and the patched native
reader allow rename/delete sharing and retry short replacement/open transitions
for at most 0.15 seconds. Persistent failures remain failures; malformed JSON,
job identity checks and acquisition outcomes are never rewritten as success.
The separate native watchdog is not modified; bounded writer retries also cover
its short legacy reads. No shipped Squid file is edited.

This addresses the October 24 cycle-7 failure: images and stage cleanup finished,
but Windows denied replacement of watchdog `run.json` at 08:06:18.065, leaving
stale running status. It does not replay imaging or resume that failed batch.

The 2026-11-12 composed-transfer run `d8a9f067c8c44c1f97b9b4c61a094c2e`
stopped before its first executor call when ReplaceFileW returned 1175 while
saving the dispatch record. The bounded identical-file retry now includes
1175 (both names remain intact per the Windows API contract). Errors 1176/1177,
which can leave partially renamed files, are not retried. Permanent failures
still stop the workflow, preserve the previous record and retain its review
hold. Regression tests inject failures before and after a step and verify no
motion is repeated. Reloading the console loads this fix for transfer logs;
the running Squid writer picks it up on its next separately approved restart.

Run `test_state_io.py` with Squid's Python from its software directory for real
Windows sharing tests plus the native `RunStateWriter` check, with no hardware.
A normal Squid restart loads the writer fix; `get_stage_reference` then reports
`state_io_version: 1`. Restart requires clearance for native startup homing.

### Loading completion and physical controller identity (2026-11-12)

The external add-on now reports `get_stage_reference.loading.version: 2`.
It records a session-local receipt only after Squid's GUI loading callback
reports success, or the approved named loading command completes. The GUI's
button label alone is not evidence: the shipped callback also updates that
label after a failed move. Stage commands and acquisition starts invalidate
the receipt; a new session, controller or reference cannot reuse it.

Loading readiness allows 0.020 mm in X/Y and 0.050 mm in Z against the taught
reference and checks that the stage remains at its completed loading position.
Thus native Z0.100 is accepted against the saved Z0.063984375 after successful
loading. These tolerances do not change imaging, robot or general arrival checks.
The actual open USB serial port supplies controller identity, rather than an
optional launcher override. Auto-detected controller 12769210 is consequently
identified without reconnecting or changing the taught reference.

Host stage status, Cellvis transfer and acquisition entry share this completion
check. The older bridge keeps its original strict coordinate check until the
add-on is loaded. Deploy with a normal Squid restart after operator clearance
for startup homing, and reload the console. Then complete Load position and
verify a fresh receipt before proposing robot transfer. No shipped Squid source,
saved loading target, robot path, or approval requirement is changed.
