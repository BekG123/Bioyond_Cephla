---
name: full-calibration-skill-48-well-plate-v1
description: Run the Cephla Bioyond 48-well plate calibration, taught alignment, descent and supervised pickup using the local Flask controller and recorded trial evidence.
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

# Full_Calibration_Skill_48_well_plate_V1

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use `.venv-realsense/Scripts/python.exe -B` and the existing Flask owner at `http://127.0.0.1:5002`. Never open a second robot SDK connection.

## Procedure

1. Read current `/state`, `/seq`, `operator_ui/plate48_workflow.py`, `projected_pickup.py` and the active pickup profile. Confirm the current request covers physical execution, the plate is in the pickup holder, claws empty, and route clear. Prior session authorization remains valid unless the setup changes. Stop on faults or uncertain payload; do not clear faults or silently retry.
2. Return Home through the existing reviewed Home planner. Empty controller startup can close the jaws: never use it with a held plate. Prepare and settle an empty controller before generating its final Home plan. Verify actual Home completion.
3. Use `calibration_e2.verify(correct=True)` through the existing workflow, targeting 1.77 degrees. Per the operator's November 9 request to restore the previous successful calibration code, require three fresh readings whose value rounded to three decimals is at least 1.769 and whose raw value is at most 1.82. Retain the existing single automatic correction. If that correction does not meet the accepted range, stop; no automatic retry or upper-bound widening.
4. POST `/seq/calibrate_48well` with `confirm`, `cell_clear`, `empty_gripper`, `plate_unchanged` true only when established. Poll completion. This uses the 48-well grid, not ArUco. Preserve placement and stability checks. A failed measurement stops this attempt.
5. Follow `trial_pickup_inward64.py` and the current reviewed wrapper for alignment and open-claw descent. Pin the fresh active profile SHA and create a new receipt directory; never reuse historical success receipts. Read the active correction instead of guessing from old messages. The Nov 3 configuration is total +Y10.4 mm from `pickup_correction.source_endpoint`, not another cumulative shift. Keep the Squid destination unchanged.
6. The trial aligns at hover, opens to 28 mm, and descends to the taught pickup endpoint. For the unchanged, previously accepted setup, the operator has requested no routine conversational visual-acceptance pause: continue the authorized sequence when current endpoint, fresh receipts and controller checks pass. Do not label an automatic check as a new human observation. Existing backend acceptance gates are separate from this skill: use genuine current operator acceptance when supplied, or an implemented repeat-workflow authorization that preserves its original evidence; never fabricate `visually_accepted` or bypass a backend gate. Changed geometry or uncertain feedback requires review. Reuse the existing grip and 5 mm proof-lift routines with bindings to THIS attempt's profile, descent and grip receipts. Existing scripts contain dated directory bindings: inspect and update a new wrapper rather than replay old evidence. Grip target 3.9 mm, existing accepted settle tolerance 0.15 mm. Do not change torque limits.
7. Current full-calibration finish supersedes the historical loaded-Home wrappers: after the 5 mm proof lift, lower 5 mm at speed 5, verify the original holder seating pose and orientation, open E1 to 28 mm, and raise the EMPTY arm 30 mm at speed 137 using `PickupHolder`. No final IDLE travel or holder rotation. Keep historical trial wrappers unchanged and do not replay them as the new full-calibration finish. Do not add a routine visual pause for this unchanged authorized sequence; stop if retention is uncertain or the operator reports a tilted plate. No controller startup with a plate. Report actual feedback separately from human observations, with receipt paths.

Calibration completion is distinct from accepted pickup and from Squid transfer. For a requested Squid approach, use the current pinned destination and `--loaded-forward-only --approach-only --transit-speed 137`; stop overhead with claws closed. The Nov 3 low descent encountered an axis-4 collision and is not a verified successful drop-off. Do not replay that descent without a separately reviewed physical correction and authorization.

Maintain original failure logs. A skill is an execution procedure, not a bypass for controller, workspace, joint, payload or human inspection gates.

Before editing code, briefly tell the operator exactly what will change. Commit and push only when an experiment yields a fully observed result worth recording in the observations document: record that observation first, then commit its relevant code and evidence. Plans, routine edits and intermediate steps stay local. Inspect staged changes, exclude credentials and unrelated work, preserve observed failures, and report the commit and push result. Do not force-push or claim success if pushing fails. Record any uncommitted dependency needed to reproduce the experiment.
