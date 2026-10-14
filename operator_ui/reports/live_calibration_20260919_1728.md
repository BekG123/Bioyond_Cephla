# Fast calibration live preflight — 2026-09-19

Outcome: blocked by controller telemetry completion timeout before calibration motion. The Fast calibration sequence was not started. This was not a convergence-limit failure.

Operator confirmed restored lighting, both disks visible, E-stop supervision, empty gripper, and clear swept area.

Offline checks: 35 Fast calibration tests passed. The simulated extended run converged after 44 observations, 294 simulated seconds and 210 mm travel, beyond the former caps.

Live camera image: `../captures/snap_0001.png`; preview: `live_calibration_preflight.jpg`. Both disks were visually confirmed and detected. Large radius 173.6 px; small radius 86.0 px.

Initial Wide solve (not a converged result): XY residual 28.5554 mm, yaw residual 2.4948 degrees, Z residual 19.8387 mm. Wide was evaluated but was not pinned by a live sequence.

Controller was initially auto, disabled, paused. An idle connection was lost before program control; reconnection and state read confirmed the unchanged pose. The old program was stopped, servos enabled, and program started. The startup torque-report job was acknowledged, but no completion reply arrived within 10 seconds. Its trigger had been consumed. No uncertain command was resent.

After the timeout, status reported running, no controller errors, and unchanged TCP pose. The program was stopped successfully; a subsequent state read confirmed stopped, servos enabled, no errors, no active sequence, and no target.

Final reported TCP: X 283.071 mm, Y 45.613 mm, Z 306.148 mm, Rz 7.518 degrees. No calibration arm-motion commands were issued. Program startup can reset the empty gripper to closed; its actual E1 position was not verified because telemetry timed out.

Next prerequisite: diagnose the controller host-point/torque-report completion handshake and obtain a successful live telemetry report before starting calibration. The timeout alone does not identify whether the cause is controller program handling, startup readiness, or reply delivery.
