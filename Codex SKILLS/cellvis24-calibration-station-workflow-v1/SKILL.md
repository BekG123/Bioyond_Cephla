---
name: cellvis24-calibration-station-workflow-v1
description: Use the accepted lid-off Cellvis P24-1.5H-N calibration reference and reusable HOME-holder Hamilton/Squid drop-off and retrieval workflow. Use for this Cellvis plate, not the 48-well calibration button, pipetting, or imaging.
---

# Cellvis 24-well calibration and station handling

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Python: `.venv-realsense/Scripts/python.exe -B`. Sole robot owner: Flask
`http://127.0.0.1:5002`. HOME is the rotating plate fixture; IDLE is the old
parking/camera-view pose. Do not open another robot SDK connection.

## Accepted evidence

`operator_ui/reports/plate_session/cellvis24_validation/accepted_sequence_20261111.json`
binds calibration, long/short-side fit and grip acceptance, Hamilton delivery,
release and retrieval, and the corrected Squid drop-off/retrieval/HOME release.
The operator confirmed secure transfers and supported seating at both stations.
Final state: plate released in HOME, E1=28, Z105.72, E2 near1.77 degrees.
Current original-orientation monitoring accepts E2 from1.740 through1.820
degrees; the commanded calibration/restore target remains1.77 degrees.

Validated profile:
`Pick and Hold/Calibration/plate_profiles/cellvis_p24_1_5h_n_validated_v1.json`.
The older `cellvis_p24_1_5h_n.json` is an immutable commissioning snapshot:
existing route hashes still bind it. Read the versioned validated profile for
the accepted outcome; do not rewrite old evidence to make old failures pass.

The commissioning included software stops and explicit recovery. Record the
accepted individual stages and final corrected round trip as successful, not
an uninterrupted endurance run. The reusable runner was tested offline; its
first future combined live repetition is still a new runner validation.

## Calibration reference and scope

The accepted Cellvis calibration used a 4x6 well-grid cross-check, measured
rim edge lines, and a perspective mapping of the original printed two disks.
Vendor Wide math supplied XY/yaw correction. Three independent median-image
bursts checked stationary repeatability. Virtual disk radii did not measure
depth, and the method did not establish A1 orientation or barcode identity.

The first open-jaw candidate was Z78.718. The operator requested3 mm lower;
Z75.718 then gripped securely at E1=3.9 and passed a5 mm proof lift at speed5.
Calibration finished by reseating, releasing28, and rising30 mm to HOME
clearance. Long-side pose approximately X312.495/Y-66.304/Z75.718/Rz89.842.

Read `operator_ui/cellvis24_observation.py` for the read-only fresh rim/grid
measurement procedure and the acceptance JSON for the actual calibration
receipts. The runner supports `--full-calibration`: visits IDLE once, restores the released
holder to1.77, takes three fresh median-image bursts at the accepted camera pose,
and verifies the 4x6 grid and projected-rim XY/yaw before alignment/descent/grip.
It reuses the accepted fixed Cellvis endpoint, not an automatically adapted one.
Reuse requires at most0.50 mm XY and0.20 degrees yaw deviation, stable
measurements and a valid grid. It performs the5 mm proof lift at5, reseats, opens28
and rises30 at137 before handling. Calibration runs once, outside all cycles.
Never call the existing48-well calibration button for Cellvis. If the plate, holder, camera or fixture placement
changes, stop reuse and re-establish the Cellvis reference with supervised
observations and trials. Do not infer acceptance from matching footprint alone.

## Full calibration and reusable handling command

Full sequence: fresh calibration once, then five Hamilton/Squid handling cycles
(omit `--execute` for an offline preview):

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_cellvis24_workflow.py --full-calibration --home-to-hamilton-roundtrip --home-to-squid-roundtrip --cycles 5 --execute
```

Start with the plate supported in HOME, empty jaws, healthy running Auto, at
IDLE or accepted Cellvis HOME clearance. At HOME jaws must already be28; at
IDLE the command opens confirmed-empty jaws automatically. The existing IDLE
planner and holder-restoration API are reused; no48-well pickup is called.
Combined calibration orchestration is offline-tested; its live run is pending.

To reuse fresh calibration and release evidence from HOME:

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_cellvis24_workflow.py --cycles 1
```

This is an offline preview, with no controller calls. To run the checked
handling sequence under operator authorization:

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_cellvis24_workflow.py --cycles 5 --execute
```

Default order is Hamilton then Squid. `--stations hamilton` or `--stations squid`
selects one station. `--source <run.json>` selects a fresh completed Cellvis
HOME release receipt; otherwise the latest reusable run is selected, falling
back only when no reusable run exists to the final commissioning release.
A failed latest run blocks execution rather than falling back to old success.
Receipts are single-use and must be no more than30 minutes old. After that,
re-establish current setup evidence; do not alter timestamps or delete failures.

`--cycles` repeats handling only; `--full-calibration` adds one initial calibration.
It does not recalibrate between cycles,
operate Hamilton liquids, run imaging, or move the Squid stage.

The backend is `operator_ui/cellvis24_workflow.py`, through
`/developer/api/cellvis24-workflow/preview` and `/start`. Preview takes
`stations`, `cycles`, and `source` (null for latest), with optional boolean
`full_calibration`. Fresh calibration requires source null and starts at IDLE
with original holder orientation; the CLI prepares this first. Start takes the exact
returned `plan` plus `ready`, `path_clear`, and `setup_confirmed` true when
established. New receipts go to
`operator_ui/reports/plate_session/cellvis24_workflows/<id>/run.json`.

## Sequence and invariants

For each selected station, each requested cycle:

1. Require stationary healthy running Auto, jaws released28, plate supported
   in calibrated HOME, and the matching accepted HOME clearance/holder angle.
2. At HOME clearance only, rotate the released holder to90.716612 degrees for
   Hamilton or1.77 degrees for Squid. Verify feedback before approaching.
3. Connect to accepted open-jaw alignment and descend. Hamilton short-side
   seat is X306.20/Y-62.88/Z76.37/Rz87.88. Squid uses the long-side HOME seat.
4. Close with approach speed10, final1 mm speed5: short-side26 then25;
   long-side4.9 then3.9. Wait for three settled readings and fresh torque/
   position feedback, then observe for delayed faults. Lift5 mm at speed5.
5. Use the pinned one-queue station route at137, with final seating/departure5.
   Hamilton endpoint is X372.43/Y-186.67/Z53.72/Rz-93.02; Squid endpoint is
   X223.94/Y373.76/Z268.77/Rz88.34 with Z293.24 crossing clearance.
6. Release28 at Hamilton or7 at Squid; return empty to HOME clearance.
7. Reapproach the same station, regrip with the same final1 mm slow closure,
   follow the exact reverse route, reseat at HOME at5, release28, rise30 at137.
8. Advance to the next station/cycle only after verified completion.

Hamilton must remain idle/parked, access open and site4 empty for delivery.
Squid must remain idle at the accepted real-stage loading pose
X0.5000625/Y0.5000625/Z0.063984375 mm, with its unchanged holder empty for
delivery. Carry forward current user confirmations of clear routes, supported
plate and E-stop supervision; `--execute` does not prove changed fixtures safe.

Do not start/restart Lua with a plate between the jaws: startup can close them
to zero. The workflow never prepares Auto, resets faults or retries uncertain
commands. On timeout/fault/grip uncertainty stop, preserve the receipt, and
resolve actual payload/contact state before a separately reviewed recovery.

## Lessons carried into code

- Immediate `grip_detected` can precede settled E1 feedback; retain it in logs,
  require fresh settled feedback, and never treat it alone as a hardware fault.
- Cellvis clearance is2 mm above the old route. The live monitor must use the
  already-validated Cellvis route ceiling, retaining vertical-line/height checks.
- High recovery connectors must pass the real queue geometry checks before
  dispatch, not just IK. Do not expand the workspace to silence a mismatch.
- Controller completion and operator-confirmed plate retention are separate
  evidence. Record operator observations after future repetitions.


## Loaded scanner ending

For the 2026-11-11 accepted measured calibration -> 5 mm proof lift -> scanner ending, use `cellvis24-calibration-scanner-v1` and `operator_ui/run_cellvis24_scanner.py --full-calibration --execute`. That workflow keeps the plate held; this station workflow instead reseats/releases at HOME. Do not interchange the two endings.
