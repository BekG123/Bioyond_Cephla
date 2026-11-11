---
name: home-squid-direct-roundtrip-v1
description: Run the reviewed 48-well plate direct HOME-holder to Squid and back route with long-side grip, without an IDLE waypoint or releasing at Squid. Includes restoring the released holder from the Hamilton orientation to1.77 degrees. Excludes imaging and Squid drop-off/retrieval.
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





# Direct HOME/Squid round trip

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use `.venv-realsense/Scripts/python.exe -B` and the sole Flask owner at
`http://127.0.0.1:5002`. Executor: `operator_ui/home_squid_transfer.py`.
HOME means the calibration holder, not IDLE (former Home).

## Evidence and scope

Forward trial `operator_ui/reports/plate_session/home_squid/edb64dd55d6642aa9c35a02320e6ffc0.json`
completed without faults; operator confirmed secure travel and supported Squid
seating in its adjacent `_operator_success.json`. Return receipt
`1d7ca15bbe0b4938bf1393c80e0ffa89.json` completed at HOME seating height with
the plate held. Operator confirmed secure return and supported HOME seating.
Release/clearance receipt `85fa2fcc98f6425a9274e7a544d740f7.json` completed
without faults. Acceptance: `roundtrip_operator_success_20261111.json` in the
same directory. This establishes one successful direct round trip with the
plate held at Squid and released back in HOME.
Do not substitute this skill for release/pickup at Squid or microscope control.

## Path and grip

Use bound current profile and Squid route hashes, not copied coordinates.
Long-side pickup includes the accepted +Y10.4 mm correction already in its
profile. Seat approximately X312.01/Y-65.48/Z73.72/Rz89.77; proof lift5 at5.
Use ReferenceGrip closure to4.9 at10 then3.9 at5, never short-side25.

After the proof lift, one mixed-speed Lua queue:
1. Rise vertically at pickup XY toZ291.24.
2. Cross toX354/Y270/Z291.24/Rz49.02.
3. Move above Squid X223.94/Y373.76/Z291.24/Rz88.34.
4. Descend vertically toZ266.77.

Speeds `[137,137,137,5]`; reverse is the exact reverse points with speeds
`[5,137,137,137]`. No IDLE stop. After reverse arrival5 mm above HOME, seat5 mm
at speed5. Release28 only with supported seating; raise empty30 at137.
The special queue profile is `squid_queue='home_holder'`; ordinary accepted
IDLE/Squid geometry and validators remain separate.

## Procedure

Read `/state`, `/seq` and payload/fixture state. Require healthy running Auto,
no competing operation, unchanged Squid loading position/holder and supervised
clear holder rotation, plate/claw sweep and route. Carry forward applicable
user confirmations. No controller startup with a held plate, fault clearing,
automatic retries or resending uncertain commands.

Forward currently begins from the completed Hamilton workflow's rotated HOME
clearance, empty jaws28 and plate released in HOME. It requires a fresh
completed `finish_home` receipt under `hamilton_dropoffs`, with matching actual
pose. POST `/developer/api/home-squid-transfer/preview` with `source` (absolute
receipt path). Inspect the bound plan. Start via `/start` with that exact
`plan`, `ready:true`, `setup_confirmed:true`, `path_clear:true` when established.

The executor rotates the released holder to absolute1.77 degrees using the
published holder interface, then verifies three readings within1.750..1.820.
Never rotate a held plate. It connects to the accepted long-side clearance,
descends, uses ReferenceGrip, proof-lifts and transfers. It stops held at Squid.
IK checks geometry and joint limits; it does not prove physical clearance.

Return uses `/developer/api/home-squid-return/preview` with `source` equal to
the new completed forward receipt and `phase:'return'`. Dispatch via `/start`
with the checked plan and the same established confirmations. It retains3.9,
checks original holder angle before HOME seating, and stops held for inspection.
After supported seating is established, preview `phase:'release_home'` using
the new return receipt; dispatch once to open28 and raise empty30.

Monitor `/seq`, measured grip/pose and errors throughout. Any uncertainty stops
the operation; never relabel a failed receipt or use old acceptance as current
plate-location evidence. Save operator retention/support observations separately
from controller completion. The current forward entry accepts the rotated
Hamilton HOME clearance; an original-orientation HOME repeat entry is not yet
implemented. Do not rotate solely to satisfy that entry or fabricate its source.
