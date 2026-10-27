# Torque-limited Grip

**2026-10-20:** The live app now uses `ReferenceGrip` staged position closure,
following the operator-accepted 3.8 mm hold and loaded Home trial. See
[Supervised_grip.md](Supervised_grip.md). The vendor torque implementation below
is retained for reference and is not the installed final Grip stage.

## Current direction: our own E1 contact logic (2026-10-19)

The operator selected an empirical E1-only approach instead of supplying the
unknown vendor ForceArray settings. `contact_grip.py` is the offline candidate:
propose one 0.1 mm position increment at speed 5, acknowledge completion, and
compare fresh stationary E1 torque against a reference at the same opening,
arm pose and speed. No six-axis force settings are written. Existing drive
limits, controller faults and arm positioning remain unchanged.

Closing pauses on the first torque anomaly; three stationary observations can
mark persistent contact for inspection, never a verified grasp. An anomaly
that disappears also stops the trial. Missing/stale feedback, a stall, changed
pose, a fault or reaching the 3.8 mm floor prevents further closing. Each trial
increment requires confirmation. No automatic lift, tightening or retry.

This is contact detection BETWEEN position moves, not force regulation during
a move. The Python module has no hardware transport and is not connected to the
live UI. The current UI still uses the blocked vendor implementation described
below; it must not silently fall back to the candidate. No hardware was moved
or controller reloaded while creating it.

Before live integration, collect matched empty-claw and operator-confirmed
contact samples, establish repeatable torque separation and freshness, then
validate the transport's fault/Stop/timeout behaviour. Do not copy synthetic
unit-test values to hardware. The old 3.8 mm records provide position evidence,
not a calibrated contact threshold. A later fast approach requires a separately
verified contact-free range; it is not inferred from the old trajectories.

Offline checks: `operator_ui/tests/test_contact_grip.py`.

## Existing installed implementation (awaiting replacement)

The existing sequence remains **Calibrate → Align → Descend → Grip**. Descend owns
all height, sideways correction and wrist positioning. The Grip module only
closes E1 and preserves E2–E6. It never approaches, lifts, releases or retries.

`torque.py` replaces position-only execution in both researcher and developer
Grip routes, including Lacry Full Calibration. The old `position_grip` job ID
is retained for UI compatibility. Previous recordings and implementation remain
available for comparison; the application instantiates `TorqueGrip`.

## Vendor source and correction

Bioyond Works Software Manual, printed pages 60–61, A.10.3–A.10.7, documents
`MoveExtJWithForce(NumArray, V, ForceArray)` and external-joint torque limits.
The actual `main/__lif.lua` in `main_hostpoint_descent_137.bin` implements this by
setting `SetExtJTrqLimit(force)` and then moving the external joints.

The old HostPoint mode 6 passed a `JointTarget` and scalar to that function,
although it reads `_a1`…`_a6` array fields. The new Device 24 uses `DefArray` for
both arguments. The malformed mode 6 is refused in the merged package. The
vendor primitive, Descend and speed-137 trajectory modules are preserved.

This is vendor **torque-limited position motion**, not a new calibrated force
servo. We have not established the vendor runtime's completion behavior under
load. A stalled/uncertain move times out and stops without re-closing. Setting
a limit is not evidence that the prior 0x3230 fault is fixed.

## Required developer configuration

Edit `torque_profile.json` using the actual vendor/controller configuration:

- `force_limits`: all six ForceArray entries, preserving the existing E2–E6 limits.
- `force_units`: the vendor-confirmed units for that API; do not assume N or N·m.
- `contact_torque_abs`: a validated threshold in `GetCJointsTrq()` feedback units.
- `closing_torque_sign`: validated feedback direction; prior recordings suggest −1.
- `source`: where those settings and their review came from.
- `reviewed`: true only after those values are verified. This is configuration
  review, not a claim of a successful physical trial.

No existing package supplies a validated ForceArray. The shipped profile is
deliberately incomplete. Do not copy synthetic test fixture values. The manual
labels `SetGripperTorqueLimit` values as percentages, but does not establish the
units of `MoveExtJWithForce`'s ForceArray; these are separate APIs.

E1 closes no farther than **3.8 mm**, at speed **5**. Contact can settle above
that floor; the old exact-position requirement is gone. No-contact, unexpected
position changes, invalid feedback or faults stop the operation. Completion
requires six stable contact samples in Lua and five seconds of passive host
position/fault observation. Contact still does not verify a secure lift.

The force limits persist in the controller, as in the vendor primitive. They
are not silently reset or raised on exit. Review their effect on subsequent
opening and travel before commissioning this profile.

## Deployment and test

1. Configure and review the profile above.
2. Build with `.venv-realsense/Scripts/python.exe -B operator_ui/build_grip_program.py`.
3. Import and publish `main_hostpoint_descent_grip_137.bin` in Bioyond Works.
4. Reload the backend when idle. Run the existing Descend; it creates a fresh,
   single-use receipt bound to the force-profile hash. Grip checks protocol 240101
   before sending a closing command. An old program never falls back to closing.
5. Supervise the first unloaded trial, then a supported-plate trial. Review
   contact, torque, delayed drive faults and holding before any lift/transfer.

All attempts are saved under `operator_ui/demonstrations/torque_grip/` with the
descent receipt, profile/hash, request token, feedback and result. The general
audit log continues recording both UI surfaces. Hardware testing and publishing
are pending; offline Lua tests exercise control flow, not physical force.

## Supervised tuning for throughput

Once the vendor's units/range and the other-axis settings are known, vary one
parameter per explicitly started trial: establish repeatable contact at speed 5,
then commission higher speeds with the selected torque limit held fixed. Record
the supported-plate inspection, faults and repeatability, not just arrival time.
`controller_elapsed_s` measures command through Lua settling; `observation_seconds`
separately records the five-second fault watch, and `total_elapsed_s` includes it.
This avoids confusing faster closing with removing verification time. A failed
or uncertain trial stops for review; no automatic increase or retry is implemented.
