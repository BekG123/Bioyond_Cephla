---
name: cellvis24-calibration-scanner-v1
description: Run the accepted Cellvis P24-1.5H-N projected calibration, long-side grip, 5 mm proof lift and loaded barcode-scanner approach. Ends holding the plate at the scanner; excludes barcode triggering and station handling.
---

# Cellvis calibration to scanner

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
Use the existing Flask owner at `http://127.0.0.1:5002`; do not open a second
robot SDK or camera connection. HOME means the rotating plate fixture;
IDLE is the former Home parking/camera-view pose.

## Accepted physical result

On 2026-11-11 the operator accepted trial
`2094a75669894864bf1efdfcb4f2c807`: projected calibration, measured alignment,
Cellvis descent, closure to E1=3.9 mm, 5 mm lift at speed 5, then loaded travel
to the scanner. The plate remained level and secure. Acceptance and hashes:
`operator_ui/reports/plate_session/cellvis24_workflows/2094a75669894864bf1efdfcb4f2c807/accepted_scanner_workflow.json`.

The commissioning used separately supervised stages, with a pre-motion JSON
serialization rejection corrected before transfer. It was not an uninterrupted
endurance test. The reusable combined CLI is offline-tested; do not label its
first future combined invocation as already physically tested.

## Execute or preview

From the repository root:

```powershell
.\.venv-realsense\Scripts\python.exe -B operator_ui\run_cellvis24_scanner.py --full-calibration --execute
```

Omit `--execute` for an offline preview. `--help` describes arguments.
`--trial-id <32-character-id> --execute` continues a fresh, completed open-jaw
Cellvis trial before its first grip attempt; it is not a failed-motion retry.
Receipts expire after 30 minutes, and grip/lift/scanner outputs are single-use.

Start at IDLE (or accepted released Cellvis HOME clearance), with the lid-off
plate seated in HOME and jaws empty, already-running fault-free Auto/Lua,
arm released, hands clear, clear loaded route and supervised E-stop.
At HOME clearance the jaws must be open to 28 mm. The CLI reuses existing
IDLE/holder preparation; it does not start Lua, reset faults or enable servos.
Do not invoke it from the loaded scanner finish position.

The runner:
1. Restores the released holder toward 1.77 degrees using existing bounds.
2. Runs shared projected-disk calibration with the Cellvis 4x6 grid and
   three fresh median-image bursts. Transports the taught grasp once by
   measured XY/yaw; preserves Cellvis Z75.72 and runtime IK checks.
3. Stops with jaws open for operator verification of even spacing, height,
   flat support and clear proof-lift path. A different plate/fixture is not
   accepted just because the footprint matches.
4. Closes 28 -> 4.9 mm at speed 10, then the final 1 mm to 3.9 at speed 5.
   These are the existing E1 commands, not the XYZ Lua queue.
5. Lifts 5 mm at speed 5, preserving grip. Requires observation that the plate
   stayed level/secure and the loaded scanner sweep is clear.
6. Executes one Lua queue at speed 137: rise vertically to Z300, cross/turn
   to scanner X80.88/Y-143.51/Rz-1.63 at Z300, lower to Z189.16.
   The receipt-bound scanner corridor temporarily permits X80; the ordinary
   workspace is restored afterward. Do not broaden the general workspace.

No reseating, IDLE visit, release or barcode trigger occurs after pickup.
Retain faults, joint/IK, grip feedback, receipt identity and route checks.
Stop on a fault, uncertain completion, changed payload or declined inspection;
do not resend Start, restart Lua with a held plate, or silently retry.

## Evidence and implementation

`operator_ui/run_cellvis24_scanner.py` orchestrates the established APIs.
`cellvis24_scanner_pickup.py` retains the accepted closure/proof-lift checks.
`cellvis24_scanner_route.py` performs the monitored queue with fresh IK.
`run_cellvis24_workflow.py --projected-calibration-trial` is its calibration
entry point; the older fixed-reference station runner has a different ending.

New summaries: `operator_ui/reports/plate_session/cellvis24_scanner_workflows/`.
Detailed frames, measurements, motion/torque/native feedback and hashed stage
receipts remain under `cellvis24_workflows/<trial-id>/`. Torque is native
telemetry, not a calibrated gripping force. Save physical success separately
from controller completion; never alter hash-bound original motion receipts.
