---
name: home-hotel-slot2-handling-v1
description: Deliver and retrieve the accepted 48-well plate between HOME and hotel slot 2 using the taught endpoint and checked Lua queues. Use for slot-2 handling or scheduler planning; excludes unvalidated upper slots.
---

# Accepted HOME / hotel slot 2 workflow

Repository: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla`.
HOME is the calibration holder, not IDLE. Use the sole Flask owner on port5002.
Manifest: `Pick and Hold/Station Handling/workflows/hotel_slot2_v1.json`.
Acceptance and preserved raw receipt hashes:
`operator_ui/reports/plate_session/hotel_slot2_loaded_teaching_20261111_234954/slot2_operator_success.json`.
The operator confirmed clean release, secure retrieval and flat HOME reseating.
This accepts the 48-well long-side profile, not arbitrary plate types or slot3/4.

Preview: `.\.venv-realsense\Scripts\python.exe -B operator_ui/run_hotel_slot2_workflow.py --action roundtrip`.
Actions: `deliver`, `retrieve`, `roundtrip`. Add `--execute` only within the
requested physical task and confirmed setup. Start with empty jaws at HOME
clearance X312.5/Y-66.3/Z105.72/Rz89.84, running fault-free Auto, unchanged rack,
plate flat in HOME for delivery or slot2 for retrieval, destination empty,
loaded route/opening/5mm lift clear, hands clear, E-stop supervised.
Carry forward applicable confirmations; do not request them again unnecessarily.

Slot2 endpoint X293.720/Y-135.351/Z295.995/Rz-0.652 is directly taught.
HOME pickup/seating and low turning corridor remain the accepted slot1 pattern.
Only outside rise/entry and corresponding retreat use the higher endpoint.
Horizontal entry/exit speed20; outside travel137; grip3.9 with last1mm at5;
pickup lift5mm at5; slot release7; HOME seating Z72.72 at5, release28.
Withdraw horizontally to X154.409 BEFORE lowering/turning. For retrieval,
lift5mm first, then withdraw horizontally at the lifted height before lowering.
Use the bound queue executor and exact scoped outside-X corridor. Never replace
an in-rack return with the generic HOME command or a vertical rise/turn.

For a plate already held and supported at slot2, use
`operator_ui/run_hotel_slot2_handling.py --action release-retrieve --execute`
only with current support/opening/retreat clearance established.
No Lua startup, fault clearing or automatic retry. Stop on uncertain grip,
arrival, fault or timeout. Preserve controller receipts separately from operator
observations; do not infer successful retention from a completed queue alone.
