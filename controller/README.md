# Controller packages

Bioyond controller program packages (`.bin`) and their build manifests live in
this directory.

- `main.bin` — customer's original controller program. Do not delete.
- `main_hostpoint.bin` — original program plus the host-point Cartesian
  extension.
- `main_hostpoint_trq.bin` — host-point program plus per-joint torque telemetry.
- `main_hostpoint_trajectory*.bin` — controller-side queued trajectory variants.
- `main_hostpoint_descent*.bin` — controller-side guarded descent variants.
- `main_hostpoint_descent_grip*.bin` — descent plus reviewed grip candidate.
- `*.manifest.json` — build provenance: source/output hashes and changed files.

Publishing is intentionally manual: import a package into a Bioyond Works
Offline Project, then use **Publish Offline Project to Controller**. Stop and
start the published program afterward; do not resume stale paused code.

Build scripts live in `operator_ui/` and write packages/manifests here by
default. Only publish reviewed packages, with the robot supervised.
# Optional mixed wrist queue (220111)

`main_hostpoint_mixed_wrist137_queue_220111.bin` adds fixed-XYZ `MoveJ` wrist
turns at controller setting137 to a mixed linear/joint queue, with one final
completion barrier. It preserves base protocol220109 and the optional220110
IDLE turn interface; legacy route commands remain `MoveL`.

Build offline with `operator_ui/build_mixed_wrist_program.py`. The host checks
the new capability before starting the opt-in Cellvis direct Hamilton trial.
Lua rejects a joint segment that translates, exceeds180 degrees, changes its
authenticated motion kind, or requests a wrist setting other than137.
Publication does not select the new route or establish its rack clearance.
No physical speed result is claimed until the supervised trial is recorded.
