---
name: squid-dropoff-pickup-v1
description: Run the accepted Bioyond 48-well plate Squid drop-off, empty return Home, pickup and loaded return Home, or requested handling repetitions. Use when the claws must release or acquire the plate at Squid.
---

# Squid drop-off and pickup V1

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use `.venv-realsense/Scripts/python.exe -B` and the single Flask owner at `http://127.0.0.1:5002`; no additional SDK connection.

## Route and handling

Use `operator_ui/reports/squid_48well_approach/closed_claw_roundtrip_plan_20261103.json`, SHA-256 `4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81`.

Home X289.97/Y62.63/Z248.02/Rz-3.88; above Home Z291.24; transit X354/Y270/Z291.24/Rz49.02; above Squid X226.317/Y375.703/Z291.24/Rz87.823; descend to **Z266.81**. Forward speeds `[137,137,137,5]`. Reverse with **one continuous vertical lift to Z291.24 at 5**, then transit/above Home/Home at 137. Do not substitute earlier endpoints or the two-part lift.

- **Drop-off:** start Home holding the plate; travel to seat, open to **7 mm at speed 5**, verify three stable samples 0.25 seconds apart within 0.15 mm, lift and return Home empty. No pickup unless requested.
- **Pickup:** start Home empty with claws at 7 mm and plate in Squid. Travel to seat, close gradually through **6, 5, 4.8, 4.6, 4.4, 4.2, 4.0, 3.9 mm at speed 5**. Verify three stable samples within 0.15 mm at each target before proceeding; continuous lift then loaded Home.
- **Repetitions:** establish initial payload. Plate in Squid/empty Home: pickup -> loaded Home -> drop-off -> empty Home. Plate held at Home: drop-off -> empty Home -> pickup -> loaded Home. Count completion only after both halves. Seven accepted handling cycles started/ended empty at Home with plate in Squid.

## Procedure

1. Read `/state`, `/seq`, `/robot_params`. Establish payload, plate location, clearance and current motion authorization from the session. Require healthy, idle, enabled, already-running Auto. Reconnect idle connection through `/connect`; do not start/reset/re-enable or clear faults. Stop for faults, uncertain retention, changed fixtures or unexpected starting pose.
2. Inspect `operator_ui/pickup_squid_home_20261103.py`, `dropoff_approach_20261103.py`, `release_empty_home_20261103.py`, `repeat_dropoff_20261103.py`, and `repeat_handling_seven_20261103.py`. Their shared `execute_continuous_squid_return_20261103.py` validates current joints, workspace/settings, pose, route hashes and grip drift. Preserve these checks and the 0.1 mm travel grip-drift limit.
3. Create fresh per-attempt directories. Dated defaults intentionally refuse already-used paths; never delete prior logs or overwrite accepted evidence. Reuse these callable functions in a small wrapper with fresh logs and accurate current authorization:
   - `pickup.main(output_dir, authorization)` for pickup/loaded Home.
   - `approach.main(output_dir)` for loaded approach only; never releases.
   - `release.main(output_dir, authorization)` after a successful approach for release/empty Home.
   - `dropoff.main(output_dir, pickup_receipt, authorization)` for combined drop-off after a matching completed pickup receipt. Bind the current pickup receipt, not an old trial's grip state.
   These functions parse process arguments: omit `--execute` for validation and supply it only for authorized execution. Release requires a fresh approach receipt, so do not invoke its dry run at Home. Validate the full geometry from current joints first, then release-stage checks at the seat before opening. For repeats, adapt the existing sequential batch wrapper to a fresh directory and requested count; never replay its historical batch directory.
4. Check pinned route and no-motion validation before dispatch. For the unchanged accepted setup, a clear request to repeat authorizes the sequence without another chat pause at every waypoint. Changed geometry or uncertain support requires assessment before release. Do not fabricate new human observations from old acceptance or bypass backend gates.
5. Log each jaw command, stable feedback, motion phase, receipt hash and final Home state. Stop at the first failed/uncertain step or operator stop. No silent retries, torque changes, tolerance widening or controller restart. Jaw feedback alone does not prove plate retention.
6. In batches, verify pickup/loaded Home before drop-off, then release/empty Home before counting the cycle or starting another. Preserve all evidence on failure and report the exact cycle/phase.
7. Report measured results and final expected plate location, then obtain physical assessment to accept the experiment. Do not label telemetry alone as a secure/level observation.

## Evidence and records

Under `operator_ui/reports/squid_48well_approach/`:

- `release_empty_home_20261103.json`: accepted initial release/empty return (`f6b365e`).
- `pickup_home_trial_20261103.json`: accepted pickup/loaded Home (`53738c7`).
- `dropoff_repeat_02_20261103/trial.json`: accepted repeat drop-off (`010dcdf`).
- `handling_seven_20261103/batch.json`: **7/7 physically accepted complete pickup/drop-off cycles**, 601.9 seconds total, 85.3-86.9 seconds per cycle; no faults/retries (`39cf035`). User confirmed everything went smoothly. Applies to this plate and fixture setup.

Acceptance is in `operator_ui/reports/trajectory_smoothing/Observations.md`; original telemetry retains its pending-assessment status. Do not rewrite historical telemetry to simulate approval.

Announce code changes briefly before editing. For fully observed experiments, record the actual result in `Observations.md`, then commit/push only relevant code/logs. Keep intermediate and unobserved trials local; preserve failures and unrelated work. Verify push success and maintain repository and installed skill copies together.
