---
name: cellvis24-scan-station-cycle-v1
description: Run the accepted Cellvis 24-well barcode registration followed by Hamilton and Squid drop-off/retrieval through HOME. Use for one handling cycle or scheduler planning; excludes recalibration, pipetting, imaging and hotel-rack loading.
---

# Registered Cellvis station cycle

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use `.venv-realsense/Scripts/python.exe -B` and the existing Flask owner at
`http://127.0.0.1:5002`. Never open a second robot SDK connection.
HOME is the rotating plate fixture; IDLE is the old parking/camera pose.

## Accepted result

The user confirmed the entire November11 cycle successful, including plate
retention and releases. The lower scanner height decoded on its first flash.
Acceptance, source hashes and full motion records are in:
`operator_ui/reports/plate_session/cellvis24_validation/accepted_registered_station_cycle_20261111.json`.
Registered plate: `SU-PRKL-P-2611-0001`, lid-off Cellvis P24-1.5H-N.
"DNA reagents" was the user's intended purpose, not an optical contents finding.
This is one accepted handling cycle, not an executed PCR or imaging experiment.

## Sequence

1. Reuse the valid Cellvis calibration/setup. Start with the plate seated in
   HOME, empty jaws28, original holder orientation, at HOME clearance
   X312.5/Y-66.3/Z105.72/Rz89.84. Require healthy running Auto/Lua and fresh
   unused HOME release evidence. Do not recalibrate automatically.
2. Use the receipt-bound long-side pickup: approach28->4.9 at10, final1mm
   to3.9 at5; verify settled grip and lift5mm at5.
3. Carry to scanner X80.88/Y-143.51/**Z163.76**/Rz-1.63 via the existing
   Z300 loaded corridor at137. This is25.4mm below the historical scanner
   height. Preserve historical189.16 receipts and derive the return from
   the actual outbound target. Do not change unrelated vendor scanner paths.
4. Trigger at most five times per presented side. Require decoded data saved
   in the plate registry, not just a beep. On five ordinary no-reads, reseat
   and release in HOME, clear the plate, rotate the released holder to181.77,
   verify angle, then present the other short side and try five times.
   On two no-read sides, return/release in HOME and stop before stations.
   Scanner timeout/transport error is not a no-read and must stop immediately.
5. After decode, return/release in HOME and restore holder1.77. If an expected
   plate ID was supplied, mismatch prevents station handling.
6. Hamilton: rotate released holder to90.716612, verify; short-side grip25
   with final1mm at5, proof lift5mm at5. Use the accepted `opposite3` rounded
   Lua route at137 with its existing slower final placement. Release28 at
   site4, return empty HOME, retrieve, return/reseat/release HOME.
7. Squid: restore released holder1.77; long-side grip3.9, proof lift5mm at5.
   Use accepted queued route at137 and slower seating/departure. Release7,
   return empty HOME, retrieve, return/reseat HOME, open28, raise30.
8. Verify completed cycle, no faults, plate released HOME, original holder
   orientation. Preserve measured completion and operator acceptance separately.

Holder original range is1.740..1.820 degrees; command target remains1.77.
Do not rotate a held plate. Retain joint/envelope, grip, arrival and timeout
checks. Faults/uncertain outcomes stop without retry or restarting loaded Lua.
The commissioned empty recovery covers the first Hamilton turn only, not any
stuck position. Hand-guiding or changed setup requires fresh setup evidence.

## Invocation and scheduler contract

Reusable entry point (omit `--execute` for a no-motion preview):

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_registered_cellvis_cycle.py --source <fresh-HOME-release.json> --purpose "DNA reagents" --expected-plate-id SU-PRKL-P-2611-0001 --execute
```

The generic wrapper uses the same live-tested phase functions; its generic
argument handling is offline-tested. Historical accepted receipts are evidence,
not renewable start permissions. Source expiry/single-use checks remain active.
Carry forward existing authorization and unchanged setup confirmations; do not
ask again between authorized phases. `--execute` cannot establish new clearance.

For scheduler planning: reserve the arm and station interfaces; require
Hamilton idle/parked, access open/site4 empty, and Squid idle at the accepted
loading reference X0.5000625/Y0.5000625/Z0.063984375. Identity, plate location,
payload, holder orientation and phase receipt must travel with the job.
One invocation completes one handling-only cycle and returns a run record.
Only advance on completed phases; do not parallelize arm movement or re-dispatch
an uncertain command. A no-read is a blocked registration, not a successful cycle.

This executor retrieves immediately and does **not** wait for instrument work.
An experiment scheduler must split delivery/retrieval around the relevant
Hamilton/Squid job IDs, await actual successful completion, and verify Squid
loading position before retrieval. Do not imply this skill installs or validates
that scheduler integration. Hotel-rack slots are not yet commissioned.

Implementation: `retry_dna_registration.Live`, `barcode_opposite_side_trial`,
`barcode_opposite_pickup`, `barcode_opposite_transport`, and
`cellvis24_workflow` with `recorded_hamilton_variant='opposite3'`.
