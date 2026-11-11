---
name: home-hamilton-dropoff-retrieval-v1
description: Run the accepted short-side 48-well plate HOME-holder to Hamilton site-4 delivery, release, empty HOME return, retrieval and HOME reseating, including requested repetitions. Does not perform calibration, Hamilton pipetting, holder rotation or Squid travel.
---

## Two-speed closing update (2026-11-11)

Operational pickup uses `operator_ui/gripper_closure.py` policy
`approach10_final1mm_speed5_v2`: approach at speed10 to E1 target+1mm,
verify arrival, then close the final1mm at speed5. From within that final
millimeter, use only speed5. Long-side48 closes to4.9 then3.9 mm; short-side
Hamilton closes to26 then25 mm. Each native Lua MoveExtJ completes before
the next command; no blending across the speed-change boundary. Release
openings, routes, endpoint checks and fault/uncertainty stops are unchanged.
No Lua republish is required; reload the host only when its state permits.

The prior single-command speed5 closure completed full calibration, but the
following short-side grip stopped at measured E1=25.174 versus target25
(outside +/-0.15), followed by an external-axis2 servo fault0x3230. Closing
speed is not established as the cause. Do not reset/retry or relabel that
handling attempt as successful. After the operator reset the arm, a fresh
supervised two-speed run completed full calibration, Hamilton drop-off/empty
HOME return/retrieval, then Squid drop-off/empty HOME return/retrieval, ending
released in HOME. No controller faults were reported; the operator confirmed
all pickups secure and all releases flat. Evidence:
`operator_ui/reports/plate_session/continuous_grip_handling_7be41e1ef6f54581b4802c58b1ba678a/run.json`
and `operator_acceptance.json` in the same folder. This acceptance covers the
unchanged reviewed fixtures/routes, not arbitrary new placements.

CLI: `operator_ui/run_plate_workflow.py` accepts `--full-calibration`,
`--home-to-hamilton-roundtrip`, and `--home-to-squid-roundtrip`; combine flags
in that execution order. Without `--execute`, it only previews. Station flags
include drop-off and retrieval, no pipetting/imaging. Fresh receipts and live
pose checks still apply; see README for starting-state requirements. The
Squid drop-off connector is `home_squid_handling.py`, separate from the direct
held-plate executor. No IDLE detour between HOME and the stations.





# HOME/Hamilton plate handling

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use `.venv-realsense/Scripts/python.exe -B`, the sole Flask owner on
`http://127.0.0.1:5002`, and `operator_ui/hamilton_holder_dropoff.py`.
HOME is the rotating calibration holder; IDLE is the former Home. No IDLE
travel or fresh calibration occurs within this handling cycle.

## Accepted evidence

November 11 trial: delivery `6a44c3894b9143fe851cf1384e4c39ea`, release
`a092d55be8c248d8b23e51c6388dbff0`, empty
return `a565911e59de484eba4332360ee7ae48`, retrieval
`1e669fcdfa164196b7ee8099d1d7aa2a`, HOME release/clearance
`22ab342aa83d4762b30f1990ea5a44bd`. JSON receipts live under
`operator_ui/reports/plate_session/hamilton_dropoffs/`; the release receipt is
`a092d55be8c248d8b23e51c6388dbff0.json`.
The operator confirmed supported release at Hamilton and secure retrieval with
the plate supported in HOME. Preserve observations separately from controller
completion. Historical receipts describe evidence, not fresh dispatch authority.

## Geometry and sequence

- Use bound revision04 routes through the accepted turning and overhead points;
  one Lua queue per direction. Travel137, final Hamilton descent/departure5.
  Preserve the exact reverse points, including its initial3.28 mm slow rise.
- Short-side grip is E1=25 mm, opening28 mm; final jaw speed5. Do not substitute the
  long-side3.9 grip or Squid7 opening. Approach at10, then close the final1mm to the recorded endpoint at5.
- Holder target is absolute E2=90.716612 degrees, with monitored +/-0.50 degrees.
  Do not rotate it during this cycle. Check it before HOME pickup and reseating;
  do not treat drift during remote travel as evidence the held plate moved.
- Five phases: `deliver` (HOME descent, grip, proof lift5 at5, Hamilton travel);
  `release` (open28 while supported); `return` (empty exact reverse, rise to HOME
  clearance); `retrieve` (empty forward approach, grip25, loaded reverse,
  reseat5 at5 in HOME); `finish_home` (release28, empty rise30 at137).
- End: plate released in HOME, empty jaws28, Z104.37 at the accepted short-side
  clearance pose. Use reference files for coordinates, not prose copies.

## Execution

Read `/state`, `/seq` and payload/fixture state. Require healthy running Auto,
no competing operation, unchanged HOME/Hamilton fixtures, Hamilton idle with
door open, site4 available, routes/jaw sweep clear and supervised E-stop.
Carry forward applicable user confirmations. Never restart Lua onto a held
plate; no fault clearing, implicit retries or controller recovery.

For a phase, POST `/developer/api/hamilton-holder-dropoff/preview` with `phase`
and the absolute completed predecessor `source` receipt. Inspect IK and the
bound reference/configuration. POST `/start` with that exact `plan` plus
`ready:true`, `setup_confirmed:true`, `path_clear:true` when established.
Monitor `/seq` and feedback; stop on fault, uncertain grip/contact, mismatch,
timeout or disconnection. Do not resend a possibly dispatched command.

The first trial used visual support/release checks. With that accepted and
unchanged fixtures, a requested batch can chain all phases under one explicit
authorization; do not ask for confirmation between every phase/cycle.
Start at released HOME clearance with a fresh completed `finish_home` receipt:

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\repeat_hamilton_holder_handling.py --source "<absolute fresh finish_home receipt.json>" --cycles 5 --execute
```

Omit `--execute` for a nonmoving description. The runner never reconnects,
enables, resets or retries. Each phase has fresh plan/completion evidence;
batch receipts are `hamilton_dropoffs/batch_*/run.json`. Count controller
completion separately from operator confirmation of secure plates. Check the
latest batch receipt before claiming any number of successful cycles.

Latest repetition evidence: `hamilton_dropoffs/batch_cc1d25096a4c4953b3015d19d21422dc/run.json` records five controller-completed cycles (25 phases). The operator confirmed all five releases stayed flat and every pickup/transfer stayed secure without slipping. Acceptance: `hamilton_dropoffs/batch_cc1d25096a4c4953b3015d19d21422dc/operator_success.json`. This establishes five successful physical cycles for the unchanged setup.
