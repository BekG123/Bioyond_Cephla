---
name: two-station-plate-handling-v1
description: Run the accepted 48-well plate cycle with release and pickup at both Hamilton and Squid through true IDLE (former Home). Use for handling repetitions or the motion portion of a separately configured instrument experiment.
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

# Accepted two-station handling

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`. Use its `.venv-realsense/Scripts/python.exe -B` and existing Flask owner at `http://127.0.0.1:5002`; no second robot SDK owner.

## Accepted sequence

Start Home holding the plate -> Hamilton release -> empty Home -> Hamilton pickup -> loaded Home -> Squid release -> empty Home -> Squid pickup -> loaded Home. Repeat the requested count. An initial seated Hamilton start can omit the first approach after validating its receipt.

Five full cycles were physically accepted November 9 local / November 10 UTC, 2026: clean releases, secure level pickups and returns, no controller errors. Execution excluding inspection pause: 611.95 seconds. Ended Home X289.970/Y62.629/Z248.019/Rz-3.880, E1=3.89885 mm. Evidence: `operator_ui/reports/squid_48well_approach/station_handling_five_20261110/`, batches `cycles_1_1/run.json`, `cycles_2_5/run.json`, separate `operator_acceptance.json` with hashes. Preserve original telemetry.

Acceptance covers Bioyond handling at Hamilton, not Hamilton's own DCG gripper, liquid handling, PCR, imaging, or changed fixtures. Older `lab_roundtrip.py` handling settings and November 3 standalone skill geometry are not this accepted implementation.

## Pinned settings

- Both releases: E1=7 mm at speed 5, three settled readings within 0.15 mm.
- Both pickups: close to4.9 at10, then3.9 at5, three settled readings at each target. Travel grip-drift limit 0.1 mm.
- Hamilton candidate `operator_ui/reports/trajectory_smoothing/hamilton_reteach_20261108/candidate.json`; SHA256 `d747003b6883dc1c2e4999cf241833756e03e379a9c753711650c293cbaafd9c`. Forward targets at137: X215.74/Y-249/Z212/Rz-0.94 -> X195.88/Y-357.36/Z212/Rz-1.90 -> seat X186.42/Y-366.27/Z45.20/Rz-1.10. Handling return first lifts5mm at5, then hover/transit/Home at137; four separately checked legs.
- Squid candidate `operator_ui/reports/squid_48well_approach/final_squid_candidate_20261108.json`; SHA256 `9805c608b92e8efcd2c046f5f06b50d79b63d7ae61ee95dcb6c948af6050d3ff`. Home -> above Home Z291.24 -> X354/Y270/Z291.24/Rz49.02 -> X223.941/Y373.761/Z291.24/Rz88.34 -> seat Z266.768. One Lua queue/direction, protocol220109, forward speeds [137,137,137,5], reverse [5,137,137,137]. Continuous lift to clearance; four MoveL targets, one final MOVFINISH.

## Execution

1. Use existing session authorization for unchanged repeats. Establish plate location, payload, supported release, unchanged holders, clear routes, hands clear and E-stop supervision. Check `/state`, `/seq`, hand-guiding and Lacry. Require healthy idle enabled already-running Auto. Reconnect idle Flask if needed; never reset/restart onto a held plate.
2. Read `operator_ui/station_handling_five_20261110.py`. Its dated outputs/IDs are consumed. Prepare a fresh wrapper and fresh IDs/directories with accurate authorization; never delete old logs to rerun. Reuse `hamilton_squid_full_repeat03_20261109.travel_hamilton`, `station_handling_five_20261110.handling`, and shared Squid approach/release/pickup functions with `squid_handling_route.CURRENT_SOURCE/CURRENT_SHA`.
3. Hamilton handling endpoints `/developer/api/hamilton-release/preview` and `/start`: body `ready`, `supported_and_clear`, candidate SHA, fresh `trial_id`, matching fresh approach `forward_trial_id`, `operation` release or pickup. Runner name remains `hamilton_release_empty_home` for both; verify result.operation and final E1. Preserve exact receipt binding, IK, joint and workspace checks.
4. Require Hamilton idle/parked/no pending errors and door access before arm entry. Squid must be stopped at accepted loading setup. Maintain one command owner: dated wrappers lack a global cross-process instrument lock. Validate before dispatch; monitor every phase and final Home. Stop on first fault, uncertain result, contact, slip or operator stop; no silent retry, fault reset, threshold widening or legacy fallback.
5. Save fresh receipts and hashes. Obtain final physical assessment separately from telemetry. Jaw readings do not establish retention. Saving this skill is not authorization for future runs.

## Instrument integration

Hamilton processing belongs after release/empty Home; wait for the exact owned job's success and verified parked/access state before retrieval. Squid imaging belongs after release/empty Home; await exact acquisition success and return to the accepted loading position before retrieval. Bind real protocol, plate definitions, deck sites, tips, volumes and imaging settings first. Do not substitute an old 24-well protocol for the current48-well plate, or claim a mock run validates PCR chemistry. One approval covers the complete reviewed sequence; changed physical setup still needs an answer.
