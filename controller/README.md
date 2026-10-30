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
