---
name: trajectory-deblur
description: Refine demonstrated robot trajectories through recorded trials and operator feedback, preserving task intent while reducing detours, unnecessary stops and entrance reversals. Use for researcher-taught paths and comparisons of replay candidates.
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

# Trajectory deblur

The user's name for this workflow is **learning via deblur of the initial human trajectory guess**. Treat a human demonstration as evidence of task intent plus possible hesitation, loops and sampling artifacts. Preserve deliberate clearance maneuvers and manipulation actions. This skill stores a reusable procedure and evidence; it does not train model weights or establish that an untested path is safe.

## Refinement loop

1. Recover the source recording, coordinate frame, fixture layout, payload, endpoints and current robot state. Separate transit, entrance, descent, grip, lift and retreat. Keep the original samples and the best accepted candidate intact. A demonstrated Home-area endpoint may differ from saved Home.
2. Read operator feedback alongside commanded and measured poses. Name the proposed change precisely in the task frame: direction, magnitude, phase and invariant endpoints. Resolve ambiguous physical directions before movement. A visible elbow/wrist retreat can occur despite monotonic TCP motion; do not claim telemetry disproves an operator's observation.
3. Diagnose before changing: distinguish dense command boundaries, real bends, human detours, controller tracking, and kinematic link motion. Group near-collinear samples before assuming that lower delays or splines are needed. Remove loops only when the shortcut's swept volume is known clear. Fewer points alone do not guarantee smoothness.
4. Make the smallest candidate that tests the feedback. Preserve entrance and contact geometry unless changing those is explicitly intended. Prefer bounded, monotonic approach changes over arbitrary endpoint offsets. Record exactly what changed and why. Do not universalize a particular height, speed, offset or waypoint count from another path.
5. Check the entire candidate, not just endpoints: IK continuity, joint/reach limits, speed, route shape, payload and fixture constraints. Collision clearance is separate from IK. Validate queue serialization and interruption behavior when executor code changes. Simulate with available geometry; state missing geometry rather than inventing clearance.
6. Execute within the user's current authorization, using the existing controller owner and monitored executor. Prior authorization persists; avoid repeating confirmations without a new material uncertainty. Saving this skill grants no future physical-motion permission. Stop on collision, contact, controller fault, unconfirmed commands or lost feedback; diagnose before any retry. Never learn by deliberately repeating collisions or disabling their protection.
7. Export each trial before the next run or backend reload. Preserve failures as well as successes. Append observations; never overwrite an earlier baseline or conflate an offline proposal with a hardware result. Bind execution to the exact reviewed candidate; keep restart/retry semantics explicit.
8. Compare task success first, then operator acceptance, clearance evidence, endpoint accuracy, reversals, pauses, travel and time. Separate controller preparation from movement; compare the same direction, endpoints, speed, payload and layout. Describe confounders when they differ. Low-rate pose logs support coarse pause/reversal measures, not strong jerk claims. Choose a best accepted candidate per task/context rather than a universal fastest path.

## Retained evidence

For this project, briefly announce proposed code changes before editing. Commit and push only when an experiment yields a fully observed result worth adding to the observations document. Record that observation first, then commit its relevant code and evidence. Keep plans, routine edits and intermediate steps local. Review staged content, exclude credentials and unrelated work, retain observed failure records, and report the commit and push result. Never force-push to resolve a rejected push.

For each iteration retain source and parent hashes; candidate coordinates; task frame/direction; explicit feedback and its interpretation; intended change; speed/executor/blending settings; validation results; execution authorization; timestamps and telemetry; completion/errors; operator acceptance (unknown until supplied); and baseline comparison limitations. Use existing project trial JSON and append-only observations rather than starting a competing log.

For this installation, read [the Hamilton case](references/hamilton-case.md) to find the existing executor, reports and examples. Reuse the procedure on new paths, not Hamilton's coordinates or exceptions. If a ranking or learned model is later requested, use these contextual comparisons as training evidence, hold out routes for evaluation, and distinguish that training from this procedural memory.
