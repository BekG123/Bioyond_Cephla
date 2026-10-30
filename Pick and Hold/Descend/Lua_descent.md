# Lua descent candidate

Researcher **Descend** includes the taught claw alignment correction for the unchanged two-disk plate. After fresh Wide Align at Z300, it adjusts XY/yaw above the plate, opens the claw, then lowers vertically to the endpoint in `corrected_endpoint.json`. The latest operator refinement is X298.780/Y-65.683/Z70.461/Rz85.671 (2026-10-17 03:38 PDT); it has passed offline path checks but has not been replayed on hardware. `correction.py` checks the full path. This is a fixed taught endpoint, not a reusable offset for a moved plate. No Lua republishing or console reload is required for an endpoint update.

Developer → **Lua Descend (137 approach)** uses `lua_executor.py` and `operator_ui/lua/mod_Descent.lua` (device 23, protocol 230101).

- Approach at speed 137, stopping 20 mm above the calibrated target.
- Final descent at speed 5, in 1 mm steps and 0.5 mm within the last 6 mm. Each step completes before torque is checked locally. This removes per-step Flask/host-point round trips; it is not continuous force control.
- Requires Auto, enabled controller, active workspace checks, aligned XY/yaw and an already open empty claw. Preserves external-axis positions. Never opens/closes the claw or lifts automatically.
- Five baseline reads at 100 ms intervals; post-step reads after 50 ms. J1 uses its last three post-step readings; J2–4 use baseline bands. Bands are max(3σ, configured floor); excessive baseline noise is rejected. Timing and thresholds still require a supervised hardware comparison.
- On torque breach, invalid feedback or arrival mismatch: no further step, retreat, grip or retry. Host requests controller Stop on an execution fault or operator Stop. Built-in collision protection remains active. Torque checks occur between slow steps, not continuously during the fast approach.

Publish `controller/main_hostpoint_descent_137.bin` through Bioyond Works, then stop/start that program as in previous deployments. The original speed-137 trajectory and host-point Lua are preserved byte-for-byte. The console must load the updated Python backend. A live protocol handshake rejects the old program before movement; no silent fallback.

This executor refuses to run from the endpoint and never returns the arm to Z300 automatically. Align/position above the plate before another supervised test. The first speed-137 Lua trial completed on 2026-10-17 in 29.6 seconds, reaching Z70.528 with no torque breach, open jaws and no grip. The backend and protocol 230101 were loaded and verified. See [observations](Observations.md) for the retained baseline, setup timeout and comparison limitations.

Offline checks: `.venv-realsense/Scripts/python.exe -B operator_ui/tests/test_lua_descent.py` (Windows); use your environment's Python on Linux. Build: `python operator_ui/build_descent_program.py`.

Researcher → Run → **Descend** now uses this tested method after a successful, fresh Align. It opens and verifies the empty claw before lowering, and requires the readiness checkbox. It does not require a Haiku key or a manually taught descent reference. An interrupted/finished descent cannot silently replay; Align is required again. Grip reference approval remains separate. The Developer Lua button remains available.
