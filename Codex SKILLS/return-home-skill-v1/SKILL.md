---
name: return-home-skill-v1
description: Return the Cephla Bioyond arm IDLE (former Home) from its measured current position through the existing reviewed planner, preserving payload and checking route feasibility.
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

# Return_Home_Skill_V1

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use the single Flask controller at `http://127.0.0.1:5002`; no second SDK connection.

1. Read `/state` and `/seq`; reconnect through `/connect` if idle-disconnected. Establish current payload and route clearance from current evidence and user authorization. Stop on active faults, an active operation, hand-guiding, or uncertain payload.
2. Read `researcher_home.py`, `ik_home.py` and current route settings when selecting a route. Home reference is X289.97 Y62.63 Z248.02 Rz-3.88; verify against current saved settings. Plan from fresh measured pose AND joints. There is no guaranteed Home path from every possible position.
3. With empty claws, normal preparation may close/reset the jaws. Prepare and settle before requesting the final plan to avoid stale start geometry. With a held plate, require an already ready controller and `preserve_gripper=true`; never run startup, release or reset to obtain Home readiness.
4. POST `/researcher/api/lacry/button/move_home` with `{}`. Inspect returned stages and start against the established request. Execute the exact fresh plan through `/researcher/api/lacry/confirm` with `ready:true` and its `plan_id`. Poll `/seq` and verify successful completion plus actual Home pose. Stop on any failure; do not retry automatically.
5. If an unresolved attempt blocks normal Home, inspect its original evidence. Do not erase history or call actual collision travel a no-travel refusal. Existing developer recovery preview/confirm APIs in `guarded_home_recovery.py` require a healthy stopped empty controller, current geometry validation and explicit reviewed-failure authorization. Use them only when their conditions are met. Otherwise report the concrete blocker and needed human correction.

Keep current workspace and joint checks intact. A request to go Home authorizes a feasible reviewed route, not fault clearing or arbitrary travel outside the envelope. Record actual completion rather than merely an accepted API request.
