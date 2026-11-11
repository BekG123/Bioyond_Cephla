---
name: home-hamilton-holder-roundtrip-v1
description: Run the accepted 48-well HOME calibration-holder to Hamilton and back route, including holder rotation and short-side pickup, without intermediate IDLE travel. Use for this holder round trip, not Hamilton liquid handling or plate release at Hamilton.
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





# HOME holder to Hamilton and back

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use its `.venv-realsense/Scripts/python.exe -B` and sole Flask owner at
`http://127.0.0.1:5002`. HOME is the rotating calibration holder; IDLE is the
former Home at X289.97/Y62.63/Z248.02/Rz-3.88. Do not substitute the older
Hamilton/Home-area or station-to-station routes.

## Accepted evidence and its limit

The operator accepted the November 10, 2026 trial as successful: fresh full
calibration, released-holder rotation, short-side pickup, Hamilton travel,
direct HOME return, stable plate retention and supported seating. Final release
was manual, verified at E1=28 mm. The automatic finish had stopped on the old
E2 guard; the final 30 mm empty clearance was NOT executed. Preserve that
distinction when reporting or training from this successful assisted run.

Evidence is under `operator_ui/reports/plate_session/home_hamilton_1794381097290532800/`,
including `operator_success.json`, `calibration.json`, and the original failed
finish receipts. Detailed executor receipt:
`operator_ui/reports/plate_session/hamilton_exchanges/e40286e1d6d24c42b218f021b6c64272.json`.
These are references, never fresh authorization or dispatch receipts.

## Execute a newly requested round trip

1. Read `/state`, `/seq`, and `/researcher/api/lacry/state`; establish plate,
   gripper, holder and route state. Carry forward the user's applicable clearance
   and E-stop confirmation. Stop on faults, uncertain contact, disconnection or
   active competing work. Do not start a stopped Lua program with a held plate.
2. If fresh calibration is requested, use `full-calibration-skill-48-well-plate-v1`.
   Visit IDLE once for the camera start when needed. Calibration finishes at HOME:
   long-side grip3.9, proof lift5 at speed5, reseat5 at speed5, release28 at seating
   height, empty rise30 at speed137. No loaded trip to IDLE afterward.
3. Use the current `operator_ui/home_hamilton_exchange.py` developer executor.
   It requires a fresh (under30 minutes) completed calibration record inside
   `operator_ui/reports/plate_session`, with `status=calibration_completed_at_HOME`,
   current `final` robot feedback, and last `phases` entry containing
   `phase=calibration`, `status=completed`, and the real completed `sequence`.
   Use live completion evidence and matching profile SHA; never relabel a failed
   receipt or bypass the fresh-clearance check.
4. POST `/developer/api/home-hamilton-exchange/preview` with
   `{"calibration_record":"<new absolute record path>"}`. Inspect the returned plan
   and its IK/envelope checks. Dispatch that exact plan once via
   `/developer/api/home-hamilton-exchange/start` with `plan`, `ready:true`,
   `path_clear:true`, `setup_confirmed:true` only when those conditions are established.
   Poll `/seq` and current feedback; do not resubmit after a timeout or failure.
5. The executor rotates the released holder counterclockwise to absolute
   E2=90.71661229181757 degrees, verifies three readings within +/-0.10 degrees,
   and then monitors within +/-0.50 degrees. The new monitoring band is an
   operator-requested, offline-tested adjustment; its complete physical automatic
   finish is not yet validated. Original-orientation calibration still targets1.77.
6. Preserve the accepted short-side pickup: alignment approximately
   X306.197/Y-62.885/Z104.368/Rz87.879, jaws28; descend30 at137 to Z74.37;
   close to E1=26 at10, then E1=25 at5; proof lift5
   at speed5. Do not confuse the short-side25 grip with long-side3.9.
7. Follow revision04 Hamilton overhead entry and its exact reverse to HOME,
   using one Lua queue per direction. Transit137; final Z55-to-Z51.72 descent5
   (reverse departure5). Keep the plate held at Hamilton. No IDLE waypoint.
   Reuse current bound reference data, not coordinates copied from this skill.
8. At HOME, verify holder angle before reseating5 at speed5, release28 while
   supported, then raise the empty arm30 at137. Rotation is prohibited while held.
   Keep angle feedback as telemetry during loaded travel away from the holder;
   enforce it again before seating. No automatic retries, fault clearing, or
   restart after uncertain motion. Keep the measured offending angle in failures.
9. Record controller completion separately from the operator's retention/seating
   observation. Record any manual assistance explicitly. A successful assisted
   run does not establish an uninterrupted automatic finish.

The E2 guard stops a trajectory; it is not proof of the cause of a later SDK
disconnect. If disconnected, inspect connection ownership/logs separately;
do not widen geometry tolerances or reconnect and replay a possibly sent move.

## Requested repetitions

Use `operator_ui/repeat_calibration_hamilton.py --cycles 5` for a nonmoving plan;
add `--execute` for the operator-authorized batch. Running it confirms the
plate is seated in HOME, jaws empty, clear routes/rotation and E-stop supervision.
At IDLE it accepts closed confirmed-empty jaws and opens to28 once at speed5,
verifying unchanged arm pose and measured opening before proceeding. At HOME it
still requires released jaws open28 before departure. It accepts IDLE or the
known released HOME seating/clearance poses, never starts/enables/resets the
controller, and stops on the first failure or uncertain opening.
A running Manual controller may switch to Auto without program restart.

Each cycle returns empty to IDLE for fresh calibration, restores E2 to1.77
through the verified Lua interface while the arm is away, then performs fresh
calibration and the complete HOME-Hamilton-HOME exchange. It ends with the
plate released in HOME, jaws28 and empty30 mm clearance. No IDLE travel occurs
during the loaded Hamilton exchange. Each cycle has fresh calibration and
exchange receipts under `operator_ui/reports/plate_session/calibration_hamilton_*`.
The five-cycle orchestration and restoration have offline coverage; do not
claim a five-cycle physical result until the new run and operator observations
actually establish it. No loop retries or artificial success receipts.

Holder restoration before each batch calibration now accepts any finite E2
readback within the published Lua range [-360,+360] degrees. It returns to the
absolute1.77-degree target without winding normalization, splitting larger
rotations into segments of at most89.5 degrees (below the controller90.01 bound).
Each segment gets a fresh capability handshake and measured arrival check; a
fault, timeout, changed arm pose or uncertain arrival stops the batch without
retrying. The arm must be at UI-accepted IDLE, jaws empty/open28, plate retained
in HOME and the complete holder rotation clear. Three final readings must meet
the existing calibration-ready band. This broad restoration applies to the
batch preparation endpoint; the ordinary calibration small-correction routine
retains its existing limits. Expanded restoration is offline-tested, not a
claim that all starting angles have been physically commissioned.
