# Position Grip

Historical implementation. The active integration now uses [Torque Grip](Torque_grip.md).
Keep the records below for comparison; they do not describe the new force-limit behavior.

After a successful Lua Descent, use **Grip** beside Descend in Researcher Teach/Run, or **4 Grip** in Developer view. Confirm plate support and centering, hands clear and E-stop supervision.

Grip sends one E1 command to **3.8 mm at speed 5**, then stops for inspection. It does not search using torque, tighten repeatedly, reopen on failure, or lift. The operator's **3.511 mm measured ideal position** remains a reference for subsequent review, not an automatically commanded tighter target.

The controller must already be Auto/enabled with its program running. Grip never starts the program, changes modes or resets the claw. General controller protection remains intact. Stop requests cancellation, but the current closing command may finish; the physical E-stop remains the emergency stop.

A successful descent creates a single-use record, valid for ten minutes. Grip checks that the arm stayed at that endpoint and the claw remained fully open. Other console actions invalidate readiness. Reload alone does not execute anything; an unconsumed record is rechecked against live status. An attempted grip consumes it before dispatch, including uncertain or failed attempts. No automatic retry.

`operator_ui/demonstrations/position_grip/` stores the descent record and each closing attempt with the target, feedback and outcome. Reaching E1 confirms position only: `grasp_verified` and `gripped` remain false until a separate pickup procedure is implemented and validated. Legacy torque-search workflows and Haiku Grip execution remain retired.

Implementation: [position.py](position.py). Validation uses fake hardware; this new integration has not been physically tested.
