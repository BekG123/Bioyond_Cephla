# Developer pickup corrections

Researcher and Developer views both contain **Home-area ↔ Hamilton**. The button
selects the direction from the measured endpoint and uses the identical tested
three-point Z212 / 3 mm entrance route at 137. It is an empty-gripper replay,
not a plate transfer or Return Home. Each press requires its readiness checkbox;
Stop requests a controller program stop. No repeat or connecting move is added.
Attempts are saved separately in `reports/trajectory_smoothing/latest_button_runs`;
an incomplete attempt blocks another button run pending developer inspection.

**Return Home** now connects the tested Hamilton departure to actual saved Home
(X289.97, Y62.63, Z248.02, Rz−3.88). The Home-area ↔ Home connection uses three
queued commands at speed 137: lift to Z300, translate and adjust wrist at that height,
then descend. **Go to Home-area** runs the reverse connection from saved Home.
Hamilton → saved Home has six commands total; its tested Hamilton portion stays
at 137. The existing Lua package supports both; no republishing is required.
The new connector passes offline IK/workspace checks but has not been physically
tested. Verify its full clearance before using either button. The workspace
exception applies only to the exact reviewed Hamilton portion.

Other Return Home starting positions now queue straight translation stages at
137 too. A lift precedes any wrist-only rotation; the existing bounded wrist
steps retain their own speed limit. Level travel stays at or above Z300, followed
by vertical descent. The full route is checked before preparation. This does not
change calibration, alignment, taught pickup, or controller homing speeds.

Only Developer view contains **Coactive learning — Descend / Grip**:

1. Under Haiku, load and review a measured Align → manual Descend → manual Grip
   reference. If the old captures do not describe a vertical descent followed by
   stationary closure, teach those stages again. Historical collision segments
   and Haiku proposals are not automatically approved references.
2. Request one reviewed Descend or Grip action, observe the result, and use the
   existing hand-guiding/operator controls to demonstrate a better endpoint.
   Descend corrections preserve XY, wrist angle and open-jaw position. Grip
   corrections preserve the descent endpoint. Hold still for capture.
3. Choose the action and **Capture corrected endpoint**. Three live readings
   check that the arm and jaws stayed still. There are no numeric target inputs.
   Supported local changes are up to 10 mm in descent height or 0.5 mm in E1.
4. Compare the recorded change. **Accept improvement** requires checking the
   vertical path and jaw clearance; **Keep previous reference** rejects it.
   Neither button moves the robot. A new base reference invalidates older-context
   corrections. Acceptance also invalidates any prior Descend-to-Grip permission.
5. Return to the taught aligned start and request Descend, then Grip separately.
   The guarded executor uses the accepted target; Haiku sees the measured
   preference history and outcomes. A change of plate/tool/frame needs new teaching.

The online update is an explicit preference for a corrected measured endpoint
over the previous endpoint in this exact setup. It updates the reference, not
Haiku's weights or a general motion policy. Reaching a jaw position does not
verify a secure grasp. Researcher view has no learning/review controls.

History is saved atomically to `demonstrations/coactive_pickup.json` after the first
capture. Original references and rejected proposals remain available. The shared
audit log retains capture/review events and Haiku exchanges. No physical test or
correction capture is started by installing this feature or loading either page.
