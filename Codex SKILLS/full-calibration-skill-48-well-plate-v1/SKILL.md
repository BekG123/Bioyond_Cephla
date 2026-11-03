---
name: full-calibration-skill-48-well-plate-v1
description: Run the Cephla Bioyond 48-well plate calibration, taught alignment, descent and supervised pickup using the local Flask controller and recorded trial evidence.
---

# Full_Calibration_Skill_48_well_plate_V1

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use `.venv-realsense/Scripts/python.exe -B` and the existing Flask owner at `http://127.0.0.1:5002`. Never open a second robot SDK connection.

## Procedure

1. Read current `/state`, `/seq`, `operator_ui/plate48_workflow.py`, `projected_pickup.py` and the active pickup profile. Confirm the current request covers physical execution, the plate is in the pickup holder, claws empty, and route clear. Prior session authorization remains valid unless the setup changes. Stop on faults or uncertain payload; do not clear faults or silently retry.
2. Return Home through the existing reviewed Home planner. Empty controller startup can close the jaws: never use it with a held plate. Prepare and settle an empty controller before generating its final Home plan. Verify actual Home completion.
3. Use `calibration_e2.verify(correct=True)` through the existing workflow, targeting 1.77 degrees; the accepted display range is 1.769 through 1.82. Do not widen this to 1.97.
4. POST `/seq/calibrate_48well` with `confirm`, `cell_clear`, `empty_gripper`, `plate_unchanged` true only when established. Poll completion. This uses the 48-well grid, not ArUco. Preserve placement and stability checks. A failed measurement stops this attempt.
5. Follow `trial_pickup_inward64.py` and the current reviewed wrapper for alignment and open-claw descent. Pin the fresh active profile SHA and create a new receipt directory; never reuse historical success receipts. Read the active correction instead of guessing from old messages. The Nov 3 configuration is total +Y10.4 mm from `pickup_correction.source_endpoint`, not another cumulative shift. Keep the Squid destination unchanged.
6. The trial aligns at hover, opens to 28 mm, and descends to the taught pickup endpoint. For the unchanged, previously accepted setup, the operator has requested no routine conversational visual-acceptance pause: continue the authorized sequence when current endpoint, fresh receipts and controller checks pass. Do not label an automatic check as a new human observation. Existing backend acceptance gates are separate from this skill: use genuine current operator acceptance when supplied, or an implemented repeat-workflow authorization that preserves its original evidence; never fabricate `visually_accepted` or bypass a backend gate. Changed geometry or uncertain feedback requires review. Reuse the existing grip and 5 mm proof-lift routines with bindings to THIS attempt's profile, descent and grip receipts. Existing scripts contain dated directory bindings: inspect and update a new wrapper rather than replay old evidence. Grip target 3.9 mm, existing accepted settle tolerance 0.15 mm. Do not change torque limits.
7. Check the grip and proof-lift results before loaded Home with `preserve_gripper=true`. Do not add a routine visual pause for this unchanged authorized sequence; stop if retention is uncertain or the operator reports a tilted plate. No controller startup with a plate. Report actual feedback separately from human observations, with receipt paths.

Calibration completion is distinct from accepted pickup and from Squid transfer. For a requested Squid approach, use the current pinned destination and `--loaded-forward-only --approach-only --transit-speed 137`; stop overhead with claws closed. The Nov 3 low descent encountered an axis-4 collision and is not a verified successful drop-off. Do not replay that descent without a separately reviewed physical correction and authorization.

Maintain original failure logs. A skill is an execution procedure, not a bypass for controller, workspace, joint, payload or human inspection gates.

Before editing code, briefly tell the operator exactly what will change. After every experiment completes or stops, commit and push its relevant code and finalized run evidence to the configured project Git remote. Inspect staged changes, exclude credentials and unrelated work, preserve failed outcomes, and report the commit and push result. Do not force-push or claim success if pushing fails. Record any uncommitted dependency needed to reproduce the experiment.
