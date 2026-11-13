# Plate identity and rack memory

The scanner and Lacry share a persistent SQLite registry at
`~/.bioyond/plates.sqlite3`. Set `BIOYOND_PLATE_DB` to use another absolute path;
every participating process must use the same value. The operator and clean-api
checkouts default to the same database. Back it up while the console and scanner
are stopped, or use SQLite's backup API.

`operator_ui/plate_registry.py` stores exact barcode strings (including leading
zeros, case and whitespace), full scanner receipts, first/last scan timestamps,
researcher-declared contents, aliases, notes, experiment and plate type. Repeated
scans retain existing annotations. Re-importing a receipt is idempotent. Every
edit has provenance and an audit event; stale revisions are rejected.

`barcode_scanner_cli.py` automatically saves successful, complete UTF-8 scanner
reads. NG, timeout, incomplete or corrupt frames never create plate identities.
A database failure is shown separately from successful decoding; the raw receipt
remains available for recovery and the CLI exits with an error.

Import earlier scanner receipts without contacting hardware:

```powershell
py operator_ui/plate_registry.py --import-scans operator_ui/reports/barcode_scanner
```

Only decoded receipts with matching raw EOT-framed bytes are accepted. The original
scanner receipt format (`response_complete` plus raw receive events) is supported.
An ID identifies the scanned label; it does not prove that label was attached to
a plate or that the plate contains a particular reagent. No contents are inferred.

## Lacry and researcher API

Lacry receives relevant plate records in its conversation context and has these
tools: `search_plates`, `get_plate`, `update_plate`, `get_rack_slots`,
`assign_plate_slot`, and `record_plate_location`. Edits require an exact existing
ID, current revision and quoted researcher statement. Contents are declarations,
not measured chemistry. Multiple search matches are returned as ambiguous.

Example conversation, after scanning a plate whose actual label is `001`:

- “Plate 001 contains DNA reagents; call it DNA stock.”
- “Reserve rack 1 slot 2 for plate 001.”
- “Which plate has the DNA reagents?”
- “I physically placed plate 001 in rack 1 slot 2.”

These are examples, not seeded inventory records.

Read endpoints:

- `GET /researcher/api/plates?q=DNA`
- `GET /researcher/api/plates/detail?plate_id=001`
- `GET /researcher/api/rack-slots`

Write endpoints: `POST /researcher/api/plates/update`, `/assign-slot`, and
`/report-location`. Bodies use the same fields as the corresponding Lacry tools.
The rack panel's **Refresh plate inventory** button displays reservations and
reported occupancy using text rendering, with no hardware calls.

## Rack and location semantics

The five existing visual shelves have logical IDs `rack:1/slot:1` through
`rack:1/slot:5`. These IDs do not commission their estimated coordinates. No rack
paths, grip settings or robot commands are added by this integration.

`assigned_slot` is a reservation. `location` is a separately recorded researcher
report, initially `unknown`. Assignments do not claim successful delivery. A slot
cannot be assigned to or reported occupied by two different plates. Clearing a
reservation does not clear its reported occupancy. Concurrent claims are checked
in a single SQLite write transaction. A restart retains historical records; it
does not prove the current physical layout.

## Clean lab API integration

In the clean-api checkout, `plan_lab_operation` accepts `plate_id`.
`run_plate_workflow` requires a known scanned ID instead of the old `P1`
placeholder. Other operations may also attach a known ID. The proposed plan
shows that ID and requires confirmation of the actual physical plate. A changed
registry revision invalidates the proposal before execution.

Run plans and transfer ledgers use the exact ID, and `plate_identity.json` stores
the registry snapshot in the run folder. Existing dataset/event collectors then
use that ID. Run starts and outcomes are linked back to plate history. Starting
an attached run sets remembered location to `unknown`; this integration does not
fabricate intermediate custody receipts or declare completed rack placement.
Motion remains subject to the existing planner and confirmation checks.

This integration is tested offline. A console process already running must be
restarted at an appropriate stopping point to load the new Python tools and API.
