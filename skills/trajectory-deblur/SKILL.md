---
name: trajectory-deblur
description: Refine demonstrated robot trajectories through recorded trials and operator feedback, preserving task intent while reducing detours, unnecessary stops and entrance reversals. Use for researcher-taught paths and comparisons of replay candidates.
---

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

For each iteration retain source and parent hashes; candidate coordinates; task frame/direction; explicit feedback and its interpretation; intended change; speed/executor/blending settings; validation results; execution authorization; timestamps and telemetry; completion/errors; operator acceptance (unknown until supplied); and baseline comparison limitations. Use existing project trial JSON and append-only observations rather than starting a competing log.

For this installation, read [the Hamilton case](references/hamilton-case.md) to find the existing executor, reports and examples. Reuse the procedure on new paths, not Hamilton's coordinates or exceptions. If a ranking or learned model is later requested, use these contextual comparisons as training evidence, hold out routes for evaluation, and distinguish that training from this procedural memory.
