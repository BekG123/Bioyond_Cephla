# Supervised grip commissioning

**Current integrated workflow:** Full Calibration now adds a 5 mm lift at speed 5 after Grip, then starts the shared Lacry Home routine immediately at translation 137 / wrist 30. The prior separate 25 mm lift is omitted. Accepted closure remains E1=3.7 at speed 5; a standalone Grip command does not lift. The new automatic sequence awaits its first live test. Hamilton/Squid local pickup/drop-off previews use E1=7 opening and the same 5 mm slow lift, but station clearance and support remain unvalidated.

**Accepted sequence, 2026-10-20:** Operator accepted **Full Calibration -> Home** with E1=3.7, a 5 mm lift at speed 5 followed by 25 mm at 137, and the existing Lacry Home route at translation 137/wrist 30. Both 5 mm and 7 mm regrip openings passed operator inspection. [Combined JSON reference](../../operator_ui/demonstrations/reference_grip/full_calibration_to_home_3p7_20261020_accepted.json) links all telemetry and acceptance records. Validation included supervised pauses and regrip comparisons; no new automatic workflow is enabled by this record alone.

**Current trial, 2026-10-20:** After the slow 3.8 mm lift also slipped, the operator requested a fresh Home -> Full Calibration at 3.7 mm. Closure completed without faults and raw torque was recorded. The requested subsequent 5 mm lift at speed 5 and 25 mm at speed 137 reached Z103.723, E1=3.70003, without controller errors. These are consecutive queue batches with a stop at the speed transition. Physical plate retention is still awaiting feedback; do not label it an accepted pickup. See [trial](../../operator_ui/demonstrations/reference_grip/e1_3p7_20261020_result.json) and [lift](../../operator_ui/demonstrations/reference_grip/e1_3p7_20261020_two_speed_lift.json).

**Latest outcome, 2026-10-20:** The operator subsequently reported that the plate
slipped and remained on its holder during the integrated pickup's Home attempt.
The controller completed its motions, but physical pickup failed. Automatic
ReferenceGrip is disabled in `fast_position_profile.json`; the live Full
Calibration entry point was checked and refuses another run. See
[failure record](../../operator_ui/demonstrations/reference_grip/full_calibration_20261020T085121Z_failed_liftoff.json).
The earlier manually commissioned successful slow-lift trial remains separate.

## Accepted reference and faster approach candidate (2026-10-20)

[`accepted_grip_reference.json`](accepted_grip_reference.json) records the accepted
E1=3.8 mm closure at speed 5, raw torque samples 95.468/96.268/95.735
(mean 95.824), arm pose, and hashed evidence for two short lifts and the loaded
Lacry Home transfer at translation speed 137 / wrist speed 30. The operator
confirmed the plate stayed level. These are empirical observations, not torque
setpoints or a calibrated force/contact threshold.

[`fast_position_plan.py`](fast_position_plan.py) prepares larger steps away from
contact: 1 mm to E1=5, 0.2 mm to E1=4, then 0.1 mm to E1=3.8.
That is 30 commands from 28 mm instead of 242, at unchanged speed 5.
[`reference_grip.py`](reference_grip.py) now connects this staged position method
to the researcher, developer and Lacry Full Calibration routes. The operator
authorized integration for supervised validation; completion of a live full
approach must be recorded separately. Fewer commands alone do not establish a
measured cycle-time improvement. Each command is followed by fresh position and
torque feedback; Stop, faults, stale settings or changed arm pose stop the chain.

The first integrated full run completed all four stages on 2026-10-20:
30 Grip increments in 50.29 s, final E1=3.80034 mm, no controller errors.
[Trial JSON](../../operator_ui/demonstrations/reference_grip/full_calibration_20261020T085121Z.json).
No lift was performed on this replacement plate; visual contact acceptance is
recorded separately from software completion.

The accepted grip pose X312.575/Y-66.200/Z73.718/Rz89.865 differs from the saved
previous descent endpoint by X+2.340/Y+0.057/Z+3.257/Rz+0.691. The operator
requested integration of that exact accepted endpoint. The previous endpoint is
archived, and the new descent profile retains the previous vision-height band
using a hash-bound reference; it corrects at Z300 before descending.
Do not add the offset blindly to future placements. The installed method is now
ReferenceGrip, not the unconfigured vendor TorqueGrip. No force limits are written.

The operator may approve a single 0.1 mm closing step, or explicitly authorize
consecutive steps. Neither mode enables the controller, changes force settings,
clears faults, opens the jaws after an uncertain result, or lifts the plate.

- `operator_ui/supervised_grip_increment.py`: one acknowledged speed-5 step,
  three fresh torque readings, then inspection. Logs every attempt.
- `operator_ui/supervised_grip_batch.py`: developer-only, Runner-owned sequence
  of speed-5, 0.1 mm steps. The current batch stops at **5.0 mm**, before the
  torque separation observed around 4.8 mm in the earlier plate-present run.
  It does not seek an accepted hold or automatically continue below 5.0.

Both require the arm to remain at the matched empty-baseline pose, with a
healthy already-running controller and hand-guiding off. Failed or uncertain
commands are not retried. Runner Stop prevents the next step; an in-flight
0.1 mm step may complete.

The batch pauses early if jaw torque leaves an empirical reference band, or
an arm joint's torque departs from its initial readings beyond the existing
configured guard. Every planned opening now requires an exact empty measurement;
missing positions reject the batch before any motion. The band uses the empty
sample range, with an allowance equal to the largest stationary spread in the
same-pose empty recording.
This is a conservative experiment stopping heuristic, **not a calibrated
force limit, commissioned contact detector, or proof of a secure grasp**.

For the supervised trial beginning at 9.8 mm, the operator explicitly reported
a considerable gap between each jaw and the plate. Its saved stationary review
therefore provides a labeled noncontact point. The optional
`use_labeled_noncontact` mode applies a fixed +6.756 raw-unit reference offset
derived from that labeled point versus the exact empty measurement. It verifies
the source trial's baseline hash, pose, opening and visual label, then checks
fresh readings against the labeled state before moving. It does not widen the
variation allowance or change controller limits. The offset stays fixed for
the entire bounded trial; it never re-tares after possible contact.

This assumes the between-run bias is approximately constant over the tested
range. A residual departure still stops the batch, and the 5.0 mm review stop
remains. This label is specific to the current setup and does not approve
unattended Grip or future plate placements.

The initial batch version used bracketing ranges between sparse measurements.
It paused at 19.8 and 10.1 mm despite the operator reporting clear jaws.
Those records remain intact. Bracketing measurements do not establish a reliable
local torque range; the revised checks require a dense local baseline instead.

Every step records pose checks, opening, fresh jaw/joint torque, reference band,
command outcome and authorization in `operator_ui/demonstrations/supervised_grip/`.
No threshold or grasp claim is inferred when a local empty reference is missing
in single-step mode.

Reference labels matter: `a63ab2b4a2724cf8bd74acba5e847c48` was corrected by the
operator to **plate present** and is excluded as an empty reference.
The short same-pose true empty recording is `00e6901c7d874083859ffeaf606cd9cc`.
The earlier local baseline `3f0b3a50b5b34bf0a4ff3d3bffc8ddd3` measures every
0.1 mm from 10.1 through 3.8 mm at the pose before the accepted centering shift.
It is not a matching reference for the corrected pose.

An explicit `operator_ui/demonstrations/grip_baseline_selection.json` selects
the reference for subsequent batches by record path and SHA-256. Selection
never scans for the newest file. Only a completed, correctly labeled empty
record at speed 5 is accepted; batch preflight still checks the actual pose
and every planned opening. A missing selection preserves the historical
fallback, whose pose/range checks still apply. Changing the arm pose requires
a new matched reference. Historical noncontact bias is not transferred to
another baseline.

Do not start a batch outside its selected reference's measured range.
Match the closing direction before comparison: in the empty test, reopening to
10.1 produced an immediate torque of 138.935, whereas approaching 10.1 in the
closing direction produced 119.201. Position alone does not specify load history.
`compare_grip_presence.py` checks these labels and matches pose/speed/protocol.

After a review stop, inspect plate position and jaw contact. A hold requires
explicit operator acceptance; any proof lift is a separately confirmed action.
