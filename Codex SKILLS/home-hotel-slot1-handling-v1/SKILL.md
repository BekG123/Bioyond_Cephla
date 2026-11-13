---
name: home-hotel-slot1-handling-v1
description: Deliver and retrieve the accepted 48-well plate between the HOME holder and hotel rack slot 1 using the checked Lua queues. Use for slot-1 handling or scheduler planning; slots 2 and 3 have separate accepted skills; slot 4 remains blocked.
---

# Accepted HOME / hotel slot 1 handling

Use the installed repository at `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`
and its sole Flask controller owner at `http://127.0.0.1:5002`.
HOME means the calibration holder; IDLE is the former parking location.
Workflow: `Pick and Hold/Station Handling/workflows/hotel_slot1_v1.json`.
Execution: `operator_ui/run_hotel_slot1_workflow.py` with the repository Python.

## Accepted evidence

One delivery and retrieval succeeded without controller faults; the operator
confirmed secure retention and flat HOME reseating. Acceptance and hashes:
`operator_ui/reports/plate_session/hotel_slot1_loaded_teaching_20261111_222406/slot1_revision5_operator_success.json`.
Raw delivery `deliveries/d5943b56e2fc4dc2be58b4c7e76a3564.json` and retrieval
`retrievals/31587435d6fa4cc1bc86068dcb9eebab.json` remain unchanged in that folder.
This accepts slot1 with the 48-well long-side profile, not other plates or slots.

## Run

Preview offline (default):
`.\.venv-realsense\Scripts\python.exe -B operator_ui/run_hotel_slot1_workflow.py --action roundtrip`
Add `--execute` only within the user's requested physical run and confirmed setup.
Use `--action deliver` or `--action retrieve` for a single phase.

The arm must start stationary at HOME clearance X312.5/Y-66.3/Z105.72/Rz89.84,
in healthy running Auto with empty jaws and no competing job. Delivery starts
with the plate seated in HOME and slot1 empty; retrieval starts with the plate
in slot1 and HOME empty. Match the unchanged rack, clear loaded sweep, horizontal
opening/withdrawal and overhead 5mm lift, hands clear and E-stop supervision.
Carry forward applicable operator confirmations. The CLI checks geometry/evidence,
normalizes only EMPTY jaws at clearance, then uses bound preview/start endpoints.
It does not initialize Lua, clear faults, move to its start, calibrate or retry.
If setup differs, resolve it; never feed arbitrary poses into these executors.

Delivery: correct released holder near1.77 degrees using the existing gate;
accepted HOME pickup to3.9mm; proof lift5mm at5; lower corridor and outside rise
at137; horizontal entry at20 to X290.878/Y-139.412/Z240.603/Rz0.752; release7mm;
withdraw horizontally at20 to X154.409 before lowering/turning; return137 to HOME.
Retrieval: approach the SAME endpoint at20, close to4.9 at10 then3.9 at5;
lift5mm at5; withdraw horizontally at20 at Z245.603; only once outside, lower
and return137; seat at HOME Z72.72 at5, release28, raise empty to clearance137.
Queue geometry and exact outside-X exception are enforced by the existing modules;
do not replace them with a generic vertical Home planner inside the rack.
A narrow approved feedback tolerance is not authorization to ignore a fault.

Stop on fault, uncertain command/arrival or grip, competing motion or timeout.
No automatic retry and no Lua restart with a held plate. Preserve each receipt;
controller completion and operator retention/seating observations are distinct.

## Higher slots

Slots2 and3 are accepted separately in `home-hotel-slot2-handling-v1` and
`home-hotel-slot3-handling-v1`; slot4 remains blocked above the workspace ceiling. Capture the stopped loaded endpoint
and raw samples, preserve slot1 baseline, then adapt its horizontal entry/exit
and outside rise/lower pattern with continuous IK and rack-clearance checks.
Do not apply a blanket Z offset to HOME pickup, HOME seating or the lower turning
corridor. A matching shelf pitch alone does not prove full arm/plate clearance.
Do not execute the earlier failed slot2 candidates as this accepted workflow.
