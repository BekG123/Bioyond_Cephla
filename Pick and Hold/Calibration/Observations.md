# Calibration observations

Recorded 2026-09-19. Both routines use the same vendor two-disk geometry.

| Difference | Original Find Disk | New Fast calibration v4 |
|---|---|---|
| Stopping | 25 iterations and a distance-based travel budget; can publish the last estimate | Continues until confirmed convergence, operator stop, or fault; no count/time/travel cap |
| Motion | Up to 40 mm XY / 15 mm Z per step, speed 15; recovery moves after lost detection | Up to 10 mm XY / 5 mm Z; speed initially 5, now 10; stationary detection retries |
| Wrist | May combine small yaw corrections with translation | Three consistent images before yaw correction; pure wrist rotation at TCP Z >=300 mm |
| Validation | Checks camera and future grasp feasibility together | Checks camera route first; Align/Descend validate the grasp separately |
| Final estimate | Includes a 10 mm height excursion for Z sampling | Requires two consecutive converged stationary images; averages their grasp estimates |

The earlier Fast version's 14-observation / 120-second / 200-mm caps are also removed; these were separate from the original routine's limits. Workspace, joint, telemetry and fault checks remain active.

Observations below are retained as separate runs, newest first. Add future runs above existing entries; do not replace earlier results.

**2026-09-21 refactored live test, 00:52:13 PDT (speed 10):** Wide passed in 66.563 seconds, 46 observations, 35 moves and 87.831 mm travel, including a ~23.8-degree wrist correction at safe height. Final residuals: XY 0.219 mm, Z 0.242 mm, yaw 0.109 degrees. Height estimates fluctuated during convergence. Startup torque reporting timed out again; state/pose were checked and two live reports passed before calibration. Envelope enabled, no controller errors, no Align or pickup. These are vision residuals, not independent physical accuracy. [Refactored live log](../../operator_ui/reports/live_fast_calibration_refactor_20260921_005213.json)

**2026-09-21 source consolidation (offline):** Calibration loop, detection, pose math and guards now live in `fast_disk.py`, starting at `start_calibration()`. All 137 related tests passed; 12 vendor solves matched pre-refactor outputs exactly. Fast speed 10 is retained; the legacy guard's intended speed-5 wrist cap is now independent. No live test or app reload was performed.

**Speed 10 test, 18:29:08 PDT:** After app reload, Wide converged from X 337.400 / Y 63.387 / Z 321.055 mm in 28.141 seconds, 14 observations, 12 moves and 71.329 mm travel. Final residuals: XY 0.288 mm, Z 0.242 mm, yaw 0.029 degrees. Different start/lighting prevent a controlled speed comparison. Startup torque reporting timed out again; state was checked and two live reports passed before motion. Envelope remained enabled; no alignment or pickup. [Speed 10 log](../../operator_ui/reports/live_fast_calibration_speed10_20260919_182908.json)

**Speed 5 retest, 18:12:29 PDT:** Wide passed in 0.906 seconds with two fresh images and zero moves, starting at the previous converged pose. Final residuals: XY 0.175 mm, Z 0.161 mm, yaw 0.055 degrees. Estimated grasp changed by 0.044 mm in XY and +0.280 mm in Z; yaw unchanged. This checks repeatability at the same pose, not convergence from a new placement. [Retest log](../../operator_ui/reports/live_fast_calibration_retest_20260919_181229.json)

**Speed 5 test, 17:37:59 PDT:** Wide converged in 47 observations, 23 moves and 72.5 seconds, with 81.1 mm accumulated travel. Final residuals: XY 0.119 mm, Z 0.000 mm, yaw 0.073 degrees. Envelope enabled; no torque timeout during calibration. These are vision residuals, not independently measured physical accuracy. No alignment or pickup was performed. [Full live log](../../operator_ui/reports/live_fast_calibration_20260919_173759/result.json)
