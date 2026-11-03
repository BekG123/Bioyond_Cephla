---
name: return-home-skill-v1
description: Return the Cephla Bioyond arm Home from its measured current position through the existing reviewed planner, preserving payload and checking route feasibility.
---

# Return_Home_Skill_V1

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use the single Flask controller at `http://127.0.0.1:5002`; no second SDK connection.

1. Read `/state` and `/seq`; reconnect through `/connect` if idle-disconnected. Establish current payload and route clearance from current evidence and user authorization. Stop on active faults, an active operation, hand-guiding, or uncertain payload.
2. Read `researcher_home.py`, `ik_home.py` and current route settings when selecting a route. Home reference is X289.97 Y62.63 Z248.02 Rz-3.88; verify against current saved settings. Plan from fresh measured pose AND joints. There is no guaranteed Home path from every possible position.
3. With empty claws, normal preparation may close/reset the jaws. Prepare and settle before requesting the final plan to avoid stale start geometry. With a held plate, require an already ready controller and `preserve_gripper=true`; never run startup, release or reset to obtain Home readiness.
4. POST `/researcher/api/lacry/button/move_home` with `{}`. Inspect returned stages and start against the established request. Execute the exact fresh plan through `/researcher/api/lacry/confirm` with `ready:true` and its `plan_id`. Poll `/seq` and verify successful completion plus actual Home pose. Stop on any failure; do not retry automatically.
5. If an unresolved attempt blocks normal Home, inspect its original evidence. Do not erase history or call actual collision travel a no-travel refusal. Existing developer recovery preview/confirm APIs in `guarded_home_recovery.py` require a healthy stopped empty controller, current geometry validation and explicit reviewed-failure authorization. Use them only when their conditions are met. Otherwise report the concrete blocker and needed human correction.

Keep current workspace and joint checks intact. A request to go Home authorizes a feasible reviewed route, not fault clearing or arbitrary travel outside the envelope. Record actual completion rather than merely an accepted API request.
