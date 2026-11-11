---
name: hamilton-squid-roundtrip-v1
description: Run the accepted 48-well plate Hamilton-to-Squid-and-back handling sequence via IDLE (former Home), including Squid release and retrieval. Use for the full physical round trip or requested repeats; this does not run imaging, liquid handling, calibration, or release at Hamilton.
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





## HOME / IDLE location contract (2026-11-10)

IDLE is the former true Home at X289.97/Y62.63/Z248.02/Rz-3.88. HOME now
means the calibration holder, with separate seating, clearance and grip poses.
Historical coordinates, controller route keys and trial hashes stay unchanged:
in the legacy procedures below, Home means IDLE unless explicitly marked HOME
holder. The old Home-area remains a distinct historical waypoint.

For a new experiment, use `operator_ui/plate_session.py` and
`Pick and Hold/plate_session_workflow.json`: full calibration once per valid
session -> grip -> lift 5 mm at speed 5 -> lower the same 5 mm at speed 5
into the unchanged HOME holder -> open E1 to 28 mm while seated -> raise the
EMPTY arm 30 mm at speed 137. Full calibration ends here, with no final IDLE
travel. Separately verify the full sweep -> orient -> verify three fresh E2
readings -> re-grip -> proof lift -> accepted destination route. The revised
calibration finish is implemented and offline-tested; its exact physical
trial is pending. Earlier 5 mm empty-clearance evidence is not that trial. Never rotate a held plate. The new near-holder
rotation is prepared, NOT yet physically commissioned; the old rotation trial
was with the arm away at IDLE. Do not substitute it as clearance evidence.

Hamilton first (selected for the next supervised trial): absolute E2 target
90.71661229181757 degrees (90.717 displayed), tolerance 0.1 degree, using the
accepted short-side E1=25 mm profile. Positive E2 from the original orientation
was observed counterclockwise from above. Do not command current E2 plus 90.
Squid first: no rotation, verify E2 around 1.77 degrees using the existing rule
`round(E2, 3) >= 1.769 and E2 <= 1.82`, and use the accepted 48-well long-side
grip. A wrong original angle requires review, not a blind no-op or re-grip.

Lacry chat uses `move_idle` for old parking and `move_home` for the new holder
preparation preview. `/researcher/api/lacry/button/move_idle` selects old
parking. Legacy developer planner `propose(['move_home'])`, controller job names
and archived scripts still refer to IDLE; do not change their recorded poses.
The new preview API is POST `/researcher/api/lacry/plate-session/plan` with
`{"first_destination":"Hamilton"}` or `"Squid"`. It is not executable until
the new released-plate placement/clearance/re-grip connection is reviewed.
Do not claim it ran or bypass the preview with old compound station travel.

Session reuse is tied to completed full calibration plus setup fingerprints.
Restart, fault/disconnection, hand-guiding, changed references or uncertain
motion invalidate reuse; physical fixture changes must also be reported.
Keep the E-stop supervised, envelope/IK and payload checks, and stop on faults,
uncertain grip/position or timeout. No automatic retries or controller restart
with a held plate. No existing trajectory was requalified by this name change.

# Hamilton–Squid full round trip

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use its `.venv-realsense/Scripts/python.exe -B` and the existing Flask owner at `http://127.0.0.1:5002`. Never create another robot SDK owner.

## Accepted sequence

Start **at Hamilton with the 48-well plate already held**:

1. Hamilton → true Home, preserving grip.
2. Home → Squid; descend to the accepted seat.
3. Open E1 to **7 mm at speed 5**; verify three settled readings, 0.25 seconds apart, within 0.15 mm.
4. Lift continuously to Squid clearance at speed 5, then return Home empty at 137.
5. Return Home → Squid with jaws at 7 mm.
6. Close to4.9 mm at10, then **3.9 mm at5**; verify three settled readings at each target.
7. Lift continuously to Squid clearance at speed 5; return Home loaded at 137.
8. Home → Hamilton at 137, preserving grip. **Finish with jaws closed.**

Home is always the connection between stations. There is no release/regrip at Hamilton in this workflow. A repeated round starts from this same held-plate endpoint. Do not add calibration, imaging, Hamilton API pipetting, or final release unless requested separately.

## Pinned geometry

Coordinates are X/Y/Z in mm and Rz in degrees. Preserve these routes, not the older coordinates in the November 3 standalone skills.

Hamilton forward, all three targets queued at speed **137**:
- Home: 289.97 / 62.63 / 248.02 / −3.88.
- Approach: 215.74 / −249 / 212 / −0.94.
- Hover: 195.88 / −357.36 / 212 / −1.90.
- Seat: **186.42 / −366.27 / 45.20 / −1.10**.

Hamilton return is the exact reverse at 137, with claws unchanged.
Candidate: `operator_ui/reports/trajectory_smoothing/hamilton_reteach_20261108/candidate.json`.
SHA-256: `d747003b6883dc1c2e4999cf241833756e03e379a9c753711650c293cbaafd9c`.

Squid forward:
- Home as above.
- Above Home: 289.97 / 62.63 / 291.24 / −3.88, speed 137.
- Transit: 354 / 270 / 291.24 / 49.02, speed 137.
- Above Squid: 223.941 / 373.761 / 291.24 / 88.34, speed 137.
- Seat: **223.941 / 373.761 / 266.768 / 88.34**, speed **5**.

Squid return is the exact reverse: continuous vertical lift to 291.24 at 5, then remaining legs at 137. Do not insert a second 5 mm lift stop.
Candidate: `operator_ui/reports/squid_48well_approach/final_squid_candidate_20261108.json`.
SHA-256: `9805c608b92e8efcd2c046f5f06b50d79b63d7ae61ee95dcb6c948af6050d3ff`.

## Execution

1. Establish current payload, fixture clearance, released arm, hands clear and supervised E-stop from the session. Existing confirmation covers unchanged authorized repeats; do not ask again at every waypoint. If scope is ambiguous, clarify whether the user wants handling or closed-claw travel.
2. Read current `/state`, `/seq`, hand-guiding and Lacry activity. Require healthy, idle, enabled, already-running Auto, hand-guiding off, and measured Hamilton seat/joints matching the reviewed route. The plate must be held, not inferred solely from E1. Reconnect an idle console through `/connect` if needed; never start/re-enable/reset the controller with a held plate.
3. Confirm Hamilton is idle, parked and has no pending errors using `/researcher/api/lacry/hamilton/status`. Establish door open, taught holder unchanged/available, and clear approach. Squid must be stationary at its accepted loading setup with an available holder. Changed stage/fixture position requires checking; do not home or move Squid as a shortcut.
4. Read the accepted orchestration in `operator_ui/hamilton_squid_full_repeat03_20261109.py`. Reuse its calls to `hamilton_reteach_trial.py`, `dropoff_approach_20261103.py`, `release_empty_home_20261103.py`, `pickup_squid_home_20261103.py` and `squid_handling_route.CURRENT_SOURCE/CURRENT_SHA`.
5. The dated script/output is already used. Prepare a fresh wrapper with a unique output directory, Hamilton trial ID and accurate current authorization. Preserve paths, speeds, limits and phase order. Use current receipts, never delete old output or relabel an old success as this attempt.
6. Hamilton endpoint `POST /developer/api/hamilton-reteach/start` accepts `ready:true`, the candidate SHA, `direction`, `trial_id`, and optional `forward_trial_id`. IDs must match `[a-z0-9][a-z0-9_-]{0,63}`. Use a fresh ID for each cycle. For its initial reverse, explicitly bind the most recent completed forward receipt: e.g. the accepted run below uses `forward_trial_id:"squid_full_repeat03_20261109"`. Do not rely on the module's dated default `OUTPUT`. Confirm that receipt's SHA, completed result and candidate match the live starting state.
7. Validate both Hamilton directions and the full Squid route without `--execute`, using measured joints and existing workspace/settings. Retain dense IK checks, exact-route checks, 0.1 mm travel grip-drift limit and all controller checks. The Hamilton station-specific corridor is already checked by its executor; do not disable or enlarge the global envelope.
8. Execute only the authorized count. Poll each phase through completion, recheck Hamilton readiness before final entry, and verify actual final endpoint. If any step fails, stop, retain its evidence and report the phase; no silent retry, fault clearing, threshold changes or continuation.
9. Obtain physical outcome assessment at the end, not a new approval at each unchanged waypoint. Save operator acceptance separately from controller telemetry. Motion success alone does not establish secure retention or seating. Saving this skill does not authorize future movement.

Do not change a running controller's motion program or publish Lua to obtain readiness. Fresh trial IDs avoid changing global log filenames and reloading the console between repeats. The existing calls do not provide a cross-process batch lock: maintain one hardware-command owner and do not run another console motion or instrument workflow concurrently.

## Accepted evidence

### Single-queue upgrade prepared November 9

First empty-gripper physical trial completed November 9 local time (November 10 UTC): forward **11.59 s**, reverse **11.47 s**, four targets and one completion barrier each, no controller errors, final true Home X289.97/Y62.63/Z248.02/Rz-3.88. Reports: `single_queue_20261110T063136Z_37051494/trial.json` and `single_queue_20261110T063206Z_1d6a19b3/trial.json` under `operator_ui/reports/squid_48well_approach/`. This supersedes the offline-only status below for empty travel; operator smoothness assessment and loaded handling with the new queue remain unverified.

The shared Squid travel executor now selects one Lua queue per direction. It requires new protocol **220109** and refuses before travel on older published programs. Forward speeds remain **137,137,137,5**; reverse speeds remain **5,137,137,137**. Geometry and jaw commands are unchanged. The accepted physical evidence below used the previous separate host moves; this upgrade is **offline tested, not yet hardware tested**.

Publish `controller/main_hostpoint_descent_grip_e2_queue_220109.bin` in Bioyond Works and load the updated Flask backend before a supervised trial. Do not restart onto a held plate. The package preserves all modules except `mod_Trajectory.lua`. The new Flask preview/start endpoints are `/developer/api/squid-queue/preview` and `/developer/api/squid-queue/start`; they require direction, fresh trial ID, exact candidate SHA and `ready:true`. Existing approach/release/pickup helpers use this shared executor automatically. Never silently fall back to legacy travel on a queue error.

For a standalone direction, `operator_ui/run_squid_single_queue.py --direction forward` (or `reverse`) previews without moving; `--execute` sends the authorized trial. Use the repository Python environment. Each direction uses four MoveL targets with individual speeds and one final MOVFINISH. Save physical acceptance separately after testing.

**November 9, 2026:** full requested round trip completed in **102.09 seconds**, no controller errors. Final Hamilton X186.420/Y−366.270/Z45.200/Rz−1.100; final grip approximately 3.893 mm. Operator: “Save this full workflow as a skill, it worked succesfully.”

- Run and child receipts: `operator_ui/reports/squid_48well_approach/hamilton_squid_full_repeat03_20261109/`.
- Subsequent physical acceptance and hashes: `operator_acceptance.json` in that directory.
- Hamilton records: `reverse_squid_full_repeat03_20261109.json` and `forward_squid_full_repeat03_20261109.json` under `operator_ui/reports/trajectory_smoothing/hamilton_reteach_20261108/`.
- Brief observation: `operator_ui/reports/trajectory_smoothing/Observations.md`.

This validates one complete handling round trip in the accepted setup, not imaging, dispensing, arbitrary station offsets or future repeat reliability. Preserve the original pending-assessment telemetry and its separate human acceptance.
