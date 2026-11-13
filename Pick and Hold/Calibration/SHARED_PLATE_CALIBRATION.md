# Shared projected-disk calibration

The 48-well and Cellvis camera paths now share the projected-disk fitting and
vendor Wide XY/yaw transform in `operator_ui/projected_plate_calibration.py`.
Their image trackers and plate profiles remain specific to each plate: a 4×6
Cellvis grid is not passed to the 48-well tracker.

Cellvis retains its accepted Z75.72 mm endpoint and E1=3.9 mm grip. The complete
taught XY/yaw relationship already includes the manual corrections; the solver
transports that relationship once from the reference observation to the current
measurement. Virtual disk size never supplies gripping height.

## Measured alignment trial

Preview without connecting to hardware:

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_cellvis24_workflow.py --projected-calibration-trial
```

Add `--execute` for a supervised open-jaw trial from the normal accepted start.
It uses the existing IDLE preparation, original holder orientation, three fresh
median-image bursts, measured alignment and descent. The complete resolved
route must pass IK and envelope checks before alignment starts. It stops with
E1=28 at the candidate gripping height, without gripping, lifting or visiting
an instrument. Existing arm preparation requirements still apply; this command
does not restart Lua or clear faults.

The trial scope is at most 1 mm of endpoint displacement and 0.5° yaw from the
taught pose. These are candidate bounds, not physically validated pickup
tolerances. Stable measurements are required independently of distance from
the old reference. The old 0.50 mm / 0.20° fixed-endpoint reuse test is retained
for the accepted `--full-calibration` workflow.

The trial ends as `awaiting_open_claw_inspection`, not a successful full
calibration or a reusable station receipt. The earlier adjusted endpoint was
visually rejected; sharing the math does not establish its physical accuracy.
The new measured path needs inspection before any grip or station integration.
Original acceptance records and the retired adjustment APIs are unchanged.

## Data flow

1. Plate-specific rim/grid tracking produces projected original disk outlines.
2. Shared math converts the disk mark into a robot-frame XY/yaw target.
3. Three observations must agree; grid coverage, residuals, finite values and
   camera centering are checked separately from fixed-reference reuse.
4. `T_live_target × inverse(T_reference_target) × T_taught_grasp` produces the
   candidate endpoint. Cellvis's accepted Z and grip setting are preserved.
5. The workflow checks the measured route with IK and sends that same endpoint
   to alignment and descent. It records the measurement, resolved route,
   implementation hashes and pending physical acceptance in `run.json`.

Normal `--full-calibration` still uses the physically accepted fixed endpoint
when its reference checks pass. It also records the shared solver's candidate
for diagnosis. The proven Hamilton and Squid routes are not silently shifted
to match an untested calibration endpoint.

## Offline replay

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\validate_shared_plate_calibration.py <saved-workflow-run.json> --output <new-report.json>
```

This reads saved observations and runs real IK without accessing hardware.
The November 11 rejected-reference replay passed IK for a candidate adjustment
of 0.422 mm / 0.253°. This is software validation, not a successful pickup.


## Accepted Cellvis pickup and scanner extension (2026-11-11)

Trial `2094a75669894864bf1efdfcb4f2c807` was physically accepted through measured alignment/descent at X312.80/Y-65.98/Z75.72/Rz90.12, E1=3.9 closure, a 5 mm lift at speed 5, and one loaded Lua queue at 137 to the scanner. The operator confirmed secure retention. `accepted_scanner_workflow.json` alongside the trial hashes the immutable stage receipts and additive observations. This validates that supervised placement, not every future pose candidate.

`operator_ui/run_cellvis24_scanner.py --full-calibration --execute` orchestrates the same stages, with physical alignment and proof-lift inspections. Omit `--execute` to preview offline. The combined CLI passes offline tests; its first combined physical invocation remains to be tested. It ends holding the plate at the scanner without reseating, returning IDLE, releasing or triggering a barcode read. Existing fixed-reference station handling is unchanged.
