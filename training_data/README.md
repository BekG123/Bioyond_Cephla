# Cephla training dataset

This folder holds versioned, structured exports of the lab's existing recordings.
Original recordings are not changed. No training, instrument operation, or robot
movement is performed by the exporter.

## Current snapshot

[snapshot_20261026T233643Z](snapshot_20261026T233643Z/) contains the first validated
export: 21,479,221 observations; 10,595,025 candidate observed-state transitions;
367,570 events; 7,696 indexed assets; 1,174 reference/metadata documents; and
Lacry's memory and revision records. Source inventory: 10,479 files, approximately
71.8 GB. The structured export is approximately 1.69 GiB, excluding referenced assets.

Full structural validation identified one transition crossing a missing/invalid
source row. That pair is preserved in `quality/excluded_transitions.jsonl` and is
excluded from the candidate transitions. The full-scan report before cleanup and
the final passing `validation.json` are both retained. All other transition rows
were retained unchanged. These counts describe logged records, not independent
successful demonstrations. Training labels and evaluation splits still need review.

Use only snapshots with a completed `dataset.json` and a passing `validation.json`.

## Build a new snapshot

From the project root on Windows:

```powershell
.venv-realsense/Scripts/python.exe -B tools/build_training_dataset.py
```

On Linux, use your Python 3 interpreter. The exporter uses only the standard library.
Every invocation creates a new `snapshot_<UTC timestamp>` directory. Existing
snapshots cannot be overwritten. New data is included only on the next export.

## Contents

| File | Contents |
|---|---|
| `dataset.json` | Counts, version, source root and limitations |
| `source_manifest.jsonl` | Source paths, sizes, SHA-256 hashes and changes during export |
| `motion/observations.jsonl.gz` | Timestamped poses, native joint values, external axes and controller validity |
| `motion/transitions.jsonl.gz` | Adjacent valid demonstration states, with intervals no greater than 1 second |
| `agent_instruments/events.jsonl.gz` | Non-polling audit events, requests, responses and instrument/trial events |
| `records/documents.jsonl.gz` | Recording metadata, results, profiles, observations and other JSON documents |
| `labels/evidence.jsonl.gz` | Explicit source outcome/review/simulation fields; no invented acceptance labels |
| `vision/assets.jsonl` | Hashed image, depth, point-cloud and simulation-array references; assets remain in their original locations |
| `memory/*.jsonl` | Read-only snapshot of Lacry memory and revisions, as context rather than ground truth |
| `splits/groups.jsonl` | Session/source groups; split assignments intentionally unassigned |
| `quality/quarantine.jsonl` | Unreadable, malformed, non-finite or oversized records, if any |
| `quality/duplicate_sources.jsonl` | Byte-identical source files to keep together during splitting, if any |
| `quality/excluded_transitions.jsonl` | Invalid next-state pairs removed after validation, if any |
| `validation.json` | Structural checks, counts and provenance validation after running the validator |

JSONL means one JSON record per line. Gzip files can be streamed with Python:

```python
import gzip, json
with gzip.open('training_data/<snapshot>/motion/transitions.jsonl.gz', 'rt', encoding='utf-8') as stream:
    for line in stream:
        example = json.loads(line)
```

Validate a completed snapshot:

```powershell
.venv-realsense/Scripts/python.exe -B tools/validate_training_dataset.py training_data/<snapshot>
```

## Data contract

- Cartesian X/Y/Z use millimeters, Rx/Ry/Rz degrees. Joints remain in their source
  convention; do not assume all joints are rotational. E1 is a controller axis
  coordinate, not measured physical jaw spacing. Torque reports are not calibrated
  contact-force labels.
- Motion transition targets are **next observed states**, not robot commands or
  demonstrations automatically approved for execution. Faulted/disconnected samples
  remain in observations; transitions crossing them or time gaps are omitted.
- `ok: true` describes only the source record's result. It does not prove a secure
  grip, an entire successful experiment, or current validity of an old reference.
  Acceptance evidence and failed trials remain available for later curation.
- Domain labels use explicit source flags or known offline-output locations. Unknown
  domains remain unknown. Real-stage/simulated-camera runs are not real microscopy.
  Model depth predictions are not independent ground-truth depth measurements.
- Routine audit GET request/response rows are excluded from the event stream;
  explicit robot observations are retained, with consecutive identical audit states
  removed. Original logs retain the omitted material. No motion downsampling is
  applied to dedicated demonstration `samples.jsonl` files.
- Source files are read only up to their inventoried byte length. Growth or changes
  are reported. A partial trailing JSON line goes to quarantine. SQLite memory is
  read in one transaction. The export is not a globally synchronized lab snapshot.
- Asset paths are relative to `source_root` in `dataset.json`; keep the original
  project alongside the export. They are indexed, not duplicated or portable alone.
  Assets changed since inventory (for example, a live `latest.jpg`) are marked
  `exclude_mutable_or_missing_source`. Verify source checksums when loading assets
  later; do not train against an overwritten file under its old annotation.
- Never randomly split individual motion samples. Review replay/duplicate lineage
  across sessions before assigning train/validation/test groups. Historical profiles
  and related replays can otherwise leak into evaluation.
- Structured secret fields and common credential strings are redacted. Review text
  and images before sharing externally; this is not a guarantee of anonymization.

The files are ready for structured loading and model-specific preparation. The first
snapshot deliberately marks training eligibility as `review_required`: choosing a
task, resolving conflicting/obsolete references, checking labels and assigning
evaluation splits still precede model training. No model has been trained.
