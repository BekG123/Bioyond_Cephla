# Exact original two-circle calibration

`sequences_original.py` is an unchanged copy of
`99ebe5d:operator_ui/sequences.py` (line-ending normalization only).
The original calibration button and `/seq/find_disk` / `/seq/find_disk_original`
call that file's `seq_find_disk` directly with the normal robot service, camera
and teach module. They do not call `OriginalDiskGuard`, `run_original_disk`,
the fast calibration loop or the edge-centering loop.

The original speeds, thresholds, correction steps, winding selection, recovery
logic, helpers and Z refinement are preserved. The added original_disk.py
wrapper remains on disk for reference but is not used by these endpoints.

Scope: calibration code only. Current robot service, controller protections,
calibration data, taught configuration files and unrelated GUI features were
not rolled back. The teach solver's local configuration path still points to
this computer, not the old author's Desktop. API operator-confirmation and
sequence-exclusivity gates remain outside the original routine.

This historical code predates the newer full-path/unknown-state wrapper and
has no added 300 mm wrist-height gate. It can recover after losing detection
and publish a last-good estimate without convergence. Review residuals and
verify the entire swept volume at the current height before a supervised
test. Restoring the file does not validate it for the current cell placement.
No live calibration was executed as part of this restoration.
