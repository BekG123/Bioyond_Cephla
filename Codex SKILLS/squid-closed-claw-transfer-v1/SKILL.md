---
name: squid-closed-claw-transfer-v1
description: Run the accepted Bioyond 48-well plate IDLE (former Home)-to-Squid travel and optional return with the plate retained and no release. Use for loaded Squid travel or closed-claw repeatability, not drop-off or pickup.
---


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

# Squid closed-claw transfer V1

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use `.venv-realsense/Scripts/python.exe -B` from the repository and the single Flask owner at `http://127.0.0.1:5002`. Never open another SDK connection.

## Accepted geometry and speeds

Coordinates are X/Y/Z in mm, Rz in degrees. Use the November 3 endpoint, not earlier Squid destinations or inferred calibration offsets.

| Point | X | Y | Z | Rz | Forward speed |
| --- | --- | --- | --- | --- | --- |
| Home | 289.97 | 62.63 | 248.02 | -3.88 | start |
| Above Home | 289.97 | 62.63 | 291.24 | -3.88 | 137 |
| Transit | 354 | 270 | 291.24 | 49.02 | 137 |
| Above Squid | 226.317 | 375.703 | 291.24 | 87.823 | 137 |
| Squid seat | 226.317 | 375.703 | 266.81 | 87.823 | 5 |

Return reverses these points: **one continuous vertical lift to Z291.24 at speed 5**, then transit/above Home/Home at 137. No intermediate stop at Z271.81. Keep claws unchanged throughout.

Pinned files under `operator_ui/reports/squid_48well_approach/`:

- `closed_claw_roundtrip_plan_20261103.json`: SHA-256 `4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81`.
- `destination_final_z266p81_20261103.json`: `ac004fd846bf2333a29f29374b7091b7c042cb6cf31d53ca09c45432412a84b8`.
- `loaded_return_continuous_lift_z266p81_20261103.json`: `269694264565a4aef4d9b53a586d80925aa222df2aca7f3fa3d6f1aa84454fb7`.

## Procedure

1. Establish payload, clearance and current execution authorization from the session. Require a securely held plate and healthy, idle, enabled, already-running Auto controller. Read `/state`, `/seq`, `/robot_params`; reconnect through `/connect` only if idle-disconnected. Never start/reset the controller, clear faults or change claws to obtain readiness. Stop for uncertain payload or changed fixtures.
2. Inspect `operator_ui/roundtrip_squid_closed_20261103.py` and `execute_continuous_squid_return_20261103.py`. Verify pinned hashes, live pose/joints, robot settings and enabled workspace. Preserve the executor's dense route checks, vertical departure using live XY/yaw, and 0.1 mm grip-drift check. Do not replace these with unchecked `/move` calls.
3. Match requested scope: forward only, reverse only or round trip. An overhead-only request stops at Z291.24; normal tested travel reaches Z266.81 without opening. Do not add descent or return beyond the request. Departure must match the relevant endpoint; near Home is not automatically Home.
4. Dated scripts have already-used outputs and intentionally refuse replay. Create a fresh trial directory and wrapper using the existing executor with fresh `PLAN`/`OUTPUT`, accurate current authorization and pinned geometry. `roundtrip_squid_closed_20261103` permits overriding its module `OUTPUT`; its historical authorization text must not be represented as a new observation. Never delete historical receipts or use an old success as the new result.
5. Validate without `--execute`, then run only the authorized operation. Round-trip speeds `[137,137,137,5,5,137,137,137]`, vertical indexes `(0,3,4,7)`; forward `[137,137,137,5]`, return `[5,137,137,137]`, each with vertical indexes `(0,3)`. Preserve the actual grip baseline; do not command 3.9 mm for this travel-only skill.
6. For repeats, run sequentially, verify Home before starting the next cycle and stop at the requested count. Stop on first failed/uncertain step; no silent retries, tolerance widening, fault clearing or startup. Report the exact cycle/phase on failure.
7. Separate controller completion from physical observation. Obtain final plate-retention assessment when accepting an experiment; no extra routine pause at each unchanged waypoint. Closed-claw travel does not validate release/pickup.

## Evidence and records

Seven observed closed-claw round trips succeeded: `operator_ui/reports/squid_48well_approach/closed_claw_seven_20261103/batch.json`. Acceptance is in `operator_ui/reports/trajectory_smoothing/Observations.md`, commit `b9f00b0`. These support this fixture setup, not arbitrary routes or automatic permission to move.

Briefly announce code changes before editing. Record fully observed experiments in `Observations.md`, then commit/push only relevant code/evidence; keep intermediate and unobserved trials local, preserve failures and unrelated work, and verify push success. Maintain repository and installed skill copies together.
