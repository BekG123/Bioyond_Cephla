# Hamilton DCG inward-motion investigation — 2026-11-09

**Finding:** the custom, slow Y-axis opening path produces inconsistent position feedback. Increasing the opening width does not address that. The exact physical/firmware cause is not yet established, because the failed runs did not record the separate encoder-position field. No motion, initialization, fault reset, servo-setting change or limit change was performed for this investigation.

## What the evidence establishes

| Test | Command/path | Recorded result |
|---|---|---|
| Empty gripper at Z150, 10 mm opening per jaw | `MoveYAbsolute`, 1 mm/s | Front position initially opened, then jumped inward; drive 1026:1:515 returned 0x0F03 and 0x0F09. No plate was present. |
| Empty gripper at Z150, coordinated open/close/reopen | `MoveToPosition`, firmware-selected Y profile | Recorded positions completed the 10 mm-per-jaw opening and maintained spacing during the lift. This is not encoder-based validation or validation of seated release. |
| Supported plate, native release | `ReleasePlate` | Reported opening of 4 mm per jaw without preliminary Z motion; operator confirmed release/clearance. |
| Seated plate, generic coordinated opening | `MoveToPosition` | Started lifting before opening; stopped. This command is not an in-place release primitive. |
| Empty gripper, 4 → 4.5 mm opening per jaw | `MoveYRelative`, 1 mm/s | Front Y jumped inward to 1.294741 mm, then reported the requested outward endpoint. |
| Empty gripper, 4.5 → 5 mm opening per jaw | Same command with additional drive-position reads | Rear reported 1.260 mm inward; front 2.187 mm inward, reaching Y1.291741. Abort sent; command nevertheless returned and final reported positions reached the targets. |

The two small-step front-jaw jump positions differ by only **0.003 mm**, although their starting positions differ by 0.5 mm. This is consistent with a position-state reset/resynchronization at move start, but does not prove that mechanism. It is not enough evidence to diagnose a mechanical reversal or a particular servo defect.

## Confirmed flaws in our diagnosis and verification

1. **We conflated two feedback fields.** `YDrive.GetPosition` and the pipettor's position report are not a substitute for recording `GetStatus.Position` **and** `GetStatus.EncoderPosition`. The previous “dual-feedback” test read the former, not the separate encoder. Its matching readings do not independently prove physical jaw travel. The earlier description of that test as confirming physical reversal was too strong.
2. **Arrival was checked against the same reported position.** A success reply and correct endpoint in that field cannot establish that both jaws actually opened. Today, ten stationary reads showed rear `Position=90.634003` versus `EncoderPosition=89.669006` mm, a 0.964996 mm difference. The operator confirmed intervening manual jaw movement, so this is evidence that the fields can differ, not proof of yesterday's cause.
3. **The host abort is too slow to be a precision motion stop.** In the latest retry, the anomaly triggered Abort 0.134 s after request. The move replied at 0.629 s; Abort replied 2.102 s after being sent. It did not prevent the rest of that small command. The anomaly preceded Abort, so Abort did not cause its onset.
4. **Simulation does not validate this behavior.** The pinned simulator directly assigns target coordinates for Y moves; its native-release simulation leaves jaw locations unchanged and clears the held flag. It does not model this controller's servo behavior or observed native 4 mm release.

## What we checked and did not find

- Independently decoded the reconstructed payload using a small `struct`-based decoder, not PLR's decoder: channel 1 **+0.5**, channel 2 **−0.5**, velocity **1.0**. No sign reversal or swapped channel is present in those bytes. This reconstructs the source's payload; there was no packet capture of the original failed request.
- The coordinator's live metadata agrees with `MoveYAbsolute`/`MoveYRelative` command IDs and parameter structure. Finding different raw-drive getter IDs does **not** prove the movement IDs are wrong.
- The pinned transport writes once, waits for a matching terminal response, and discards unmatched/broadcast responses. No hidden command retry is present in that path.
- The native application's saved RCE trace covers the failure times and contains no outgoing native-application commands after 12:45 UTC on November 8. This argues against that application competing with these tests; it is not a network-wide exclusion of every possible client.
- Failure reproduced without a plate and before a lift. Plate thickness, source-site offset, holder contact with the plate, and a later retreat command are not sufficient explanations for that empty-test anomaly.
- The native release worked under the same automatic-pause setting; no evidence identifies that setting as the cause.

## Firmware compatibility findings

Instrument PRPGJ2494 reports **MLPrep Runtime V4.5.14.740**, with both channels running **NGC Runtime V2.2.6.260**. The pinned toolkit includes legacy examples/characterization on older Prep firmware, so successful examples are not a validation of all low-level commands on these channels.

The actual channel roots are `Ngc`, not the helper's default `Channel Root`. The NGC Y-drive `GetPosition` is method **18**, not the helper's hard-coded **9**. The read-only audit resolves methods by live metadata and restricts execution to allowlisted status requests. The attempted old getter was rejected; it was not used to command movement.

Neither the local metadata nor the available REST error history provided an authoritative description of the two old NGC fault codes. We must not label them using an unrelated Nimbus error table. The native application's historical errors also do not contain these direct-TCP motion failures.

## Most plausible explanations, still hypotheses

1. A position-counter/encoder discrepancy is exposed or resynchronized when the low-level Y move starts. The repeatable front-jaw jump supports investigating this first.
2. The explicit **1 mm/s** Y profile behaves differently from native release or coordinated travel on these NGC channels. Friction/following error, trajectory generation and firmware compatibility remain possible; there is no controlled speed sweep or encoder trace to choose between them.
3. Mechanical/tool coupling or drive calibration could contribute to failure to follow. Empty-jaw failure excludes a plate as necessary, but does not exclude the gripper tool or mechanism.

## Next discriminating test — not executed

First establish a clear empty-tool pose and a stable encoder baseline, using the supported recovery procedure if needed. Do not change servo tuning, force/current settings or limits to make the test pass.

Record, per drive and with timestamps: `GetStatus.Position`, `GetStatus.EncoderPosition`, coordinator destination, reported jaw position, command request/reply and errors. Pair this with a fixed camera view/scale. Run one bounded, supported small opening under supervision; do not use delayed `MethodAbort` as the only protection against a large move.

- **Counter jumps, encoder does not:** reporting/state-resynchronization problem; the old “inward movement” estimate was not physical travel.
- **Counter moves outward, encoder does not follow:** physical following/drive/mechanical issue.
- **Both move inward:** actual reversal; compare requested destination/profile with the drive trajectory and obtain firmware-specific guidance before enlarging travel.

Only then compare a different supported profile or native release. After physical clearance is verified, test an explicit retreat that preserves jaw spacing. A generic coordinated XYZ command already demonstrated an unwanted preliminary lift at seating height; it should not replace release there.

## Evidence and reproducibility

- [Computed analysis](analysis.json): signs, timing, repeated-jump values, encoder discrepancy and limitations.
- [Read-only audit](readonly_firmware_audit_final.json): actual firmware metadata, status fields and settings, with no changes applied.
- [Historical native errors and RCE trace](historical_errors_and_rce.json).
- [Last failed retry](../dcg48_repeat_683af88d0e764de8b7a8617903ffd172/dual_feedback_retry_result.json).
- [Native supported release](../dcg48_repeat_683af88d0e764de8b7a8617903ffd172/native_supported_release_result.json).
- Source: `operator_ui/analyze_hamilton_inward_motion.py`; three offline decoder/feedback tests passed. `audit_hamilton_release_readonly.py` permits no motion commands.
- The upstream [Prep documentation](https://docs.pylabrobot.org/dev/user_guide/00_liquid-handling/hamilton-prep/prep_basic_demo.html) describes its example simulator as based on PRPAA1087/V1.2.2; it is not evidence that this hardware's opening transient is simulated.
