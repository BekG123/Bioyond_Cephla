# Shared run dataset

The facade writes the same event envelope for Bioyond, Hamilton and Squid. Motion
scripts and owner-edited machine manifests are unchanged. The event schema remains
`schemas/event.schema.json`, version 1. Install the file/capture dependencies with
`py -m pip install -r labfacade/requirements-dataset.txt`.

```text
runs/<UTC>_<slug>/
  run.json                 plan, versions, manifest hashes, signed approval snapshots
  approval.json            authoritative signed approval (checked by the runner)
  attestation.json         authoritative current presence record
  human.jsonl              signed confirmations and other human actions
  events.jsonl             append-only shared events, flushed/fsynced per line
  ledger.json              plate location at facade transfer boundaries
  artifacts.json           source-to-copy mapping, hashes, machine/step and metadata
  dataset.json             per-step collection completeness and explicit gaps
  frames/<step>/           unique before/after PNG inspection images
  bioyond/<step>/<unique>/  copied receipts and raw transport/stdout journals
  hamilton/<step>/<unique>/ copied owner-ticket journals and transport facts
  squid/<step>/<unique>/    raw journals, native acquisition receipt, OME-Zarr stores
```

Machine IDs in events remain `bioyond_s4`, `hamilton_prep`, and `squid`; folder aliases
are recorded in `run.json`. Old datasets remain readable. Each artifact copy gets
a unique directory, including repeated source filenames within the same step.
Artifacts are immutable after publication; collecting again creates a new copy.

## Automatic collection

Every **dispatched** facade step, including reads and failed/timed-out operations,
attempts before/after inspection frames and collects evidence. Refused/waiting steps
do not trigger camera requests. Missing or stale images, missing receipts, rejected
paths and failed collection produce explicit anomalies and an incomplete entry in
`dataset.json`. A camera failure does not invent a machine failure or re-run motion.
Controller completion and dataset completeness are separate facts.

Real backends use `ConsoleFrame` to GET `/frame` from the existing operator console.
It converts the JPEG to an actual PNG, rejects the console's `X-Error` stale/released
camera response, and records the source URL. This is a **shared cell inspection
view**, not proof that every station or microscope sample is visible. Configure a
different read-only frame callback through `DatasetSources` when a station has its
own owner-provided view. There is no second camera SDK connection or camera restart.
The endpoint can serve a frame cached for up to 0.6 seconds; precise hardware image
timestamps are not exposed by that endpoint.

Every captured PNG also gets an `inspection_detail_v1` content check. Images smaller
than 32 pixels on either side, or with fewer than 0.1% adjacent grayscale differences
of at least 8/255 after thumbnailing to at most 256x256, produce a
`frame_quality_suspect` gap. The original image is still saved and hashed. This is a
conservative low-detail warning, not a visibility, focus, or plate-retention detector.
A passing check does not establish that the scene is useful. Camera positioning and
the physical view still need operator assessment; the logger never changes a camera
or robot pose to improve the image.

Backend transport facts and CLI stdout are journaled using the run clock. After a
timeout, the journal is closed before hashing so late replies cannot change the
published file. This does not stop or retry hardware. The Bioyond collector follows
explicit receipt references under the execution checkout's report roots, with cycle
detection and a 256-file bound. It never edits original reports. Their original
absolute references remain intact; `artifacts.json` maps source paths to portable
copies. Limits, missing sources and disallowed paths are reported rather than hidden.

Hamilton collection reads the existing wrapper's owned `request_id` journal when
available; it never searches for the newest run or reads/writes/deletes `active.json`
or the execution lock. Explicit extra journals can be supplied through
`DatasetSources(journals=[...])`. These are labelled with their source paths; callers
must supply journals belonging to the intended operation, not arbitrary history.

Compound workflow progress retains the original output and adds stable `phase_id`,
phase label, cycle and plate IDs under `data`. The ledger remains authoritative at
the facade step boundary; intermediate station movements are represented by the
packaged phase receipts, not guessed from text messages.

Bioyond receipt roots also include the specific `operator_ui/demonstrations/pickup_holder`
and `operator_ui/demonstrations/reference_grip` folders used by the workflow. Explicit
clearance/grip/descent/alignment receipt bindings are followed. The overloaded `source`
field is followed only when path-shaped; labels such as `button` are facts. A missing
path-shaped source still produces a gap. Collection parses the hashed snapshot, not
a second read of the original file.

## Imaging handoff

Squid acquisition itself is still unbound in the real backend. The **dataset
handoff** is implemented independently and sends no instrument commands:

```python
facade.collect_acquisition(
    run, step_id="s03",
    receipt="/explicit/path/to/native/run.json",
    expected_run_id="the-native-acquisition-id-bound-to-this-step",
    output_roots=["/explicit/allowed/acquisition/output/root"],
)
```

The native Squid receipt must have `schema_version: 1`, the exact expected `run_id`,
`status: completed`, `ended_at` and `output_path`. This records receipt-reported
completion, not a fresh hardware observation. An operation wrapper can automate the
same handoff by supplying `DatasetSources(acquisitions=[{...}])` with `receipt`,
`expected_run_id` and `output_roots`. `images=[...]` supports explicitly nominated,
already-finalized stores without asserting an acquisition identity.

The collector accepts the supported **OME-Zarr 0.5 / Zarr v3 image and HCS profile**:
namespaced OME metadata, consistent version, group-level multiscales, matching axis
and array dimension names, 2–5 dimensions, scale/translation transforms, and valid
plate/well/image references. It rejects 6D FOV layouts, an explicit incomplete flag,
unsafe references, changed files during copying, and symbolic links. TIFF is never
converted or relabelled OME. Validation covers metadata structure and byte integrity;
it does not decode every codec, certify scientific content, or prove all expected
fields were acquired. Sparse Zarr chunks are legal.

Specification reference: https://ngff.openmicroscopy.org/0.5/

Each directory gets a **file manifest** containing every member's relative path,
size and SHA-256. The event's `{path, sha256}` refers to that manifest file, preserving
the existing event schema. Its `root` identifies the neighboring copied store.

Squid format reporting runs automatically for Squid steps and the plate workflow's
embedded Squid reader. `--squid-software` / `--squid-config` select file sources in
the live launchers; otherwise the directory follows `SQUID_SOFTWARE_DIR` or the
existing Desktop installation convention. TIFF, conflicting/unknown formats and
6D settings produce warnings. Reports explicitly say `runtime_verified: false`:
reading an INI does not establish what the running process loaded. Actual stores
are validated separately on ingestion. No configuration files are modified.

## Numeric payloads and verification

NumPy array payloads are externalized into uncompressed numeric Zarr v3 arrays;
events contain a relative manifest reference, shape and dtype instead of stringified
pixels. These general arrays are **not labelled OME imagery** without OME metadata.
Ordinary JSON lists (steps, axes, coordinates, observations) remain facts. Binary
objects and unknown Python objects are not silently stringified. Inspection PNGs
are the explicit image exception; scientific microscopy stores use OME-Zarr.

```powershell
py -B -m labfacade.verify_dataset path/to/run
```

This offline command checks every event against the unchanged schema, run identity,
sequence ordering, artifact hashes, directory inventories, and supported OME
metadata. It reports torn lines, missing or changed files. It does not repair logs,
validate approval signatures without the owner key, or contact any hardware.

For a completed or paused plate workflow, missing referenced receipts can be backfilled
without hardware access (ensure there is no other writer for the run):

```powershell
py -B -m labfacade.reconcile_dataset path/to/run --checkout path/to/execution-checkout
```

This requires a terminal result/pause and an already-hashed root workflow receipt.
It archives the prior `dataset.json`, reuses unchanged hashed receipts, collects newly
reachable receipts, reviews existing inspection frames, and appends reconciliation
events. Previously collected receipts whose source bytes changed produce gaps rather
than replacing history. Original events, images, approvals and ledger are preserved.
`dataset.json` becomes the current collection assessment; old anomalies remain in the
event log. A successful integrity check can coexist with incomplete collection or
suspect images. No image is recaptured and no acquisition or motion is dispatched.

One facade clock timestamps events and new transport facts; original instrument
timestamps remain raw evidence. `mono_ns` supports durations within a process, not
across reboots. Logging currently assumes one run writer; concurrent service writers
and restart orchestration are not implemented by this dataset increment.

## Verification status

Offline tests cover three-machine fake runs, real-backend stub transports, PNG
conversion/stale-frame rejection, success/failure/timeout/read paths, receipt graphs,
duplicate filenames, source confinement, array extraction, OME handoff, 6D/TIFF and
incomplete-output rejection, and post-copy tamper detection. Tests prohibit live
lab ports and non-loopback connections. Symlink tests skip when Windows denies link
creation. The plate-handling integrations have also been exercised as described below;
the post-run fixes and reconciliation path were tested offline only.

The live retry `20261111T155635Z_plate-workflow` completed one calibration plus ten
handling phases through the new logging hooks: 101 initial events and 15 initial
artifacts verified. It exposed provenance-label/path confusion, missing demonstration
receipt roots, and low-detail camera images. These collection fixes were validated
offline and can be applied to the saved run with the reconciliation command above.
Both the failed attempt `20261111T155047Z_plate-workflow` and successful retry have
been reconciled from their local receipts. The retry now has 109 events and 19
verified artifacts (including its prior completeness summary); no receipt-collection
gaps remain. Both before/after frames are explicitly flagged as low detail.
The physical camera view remains unsuitable for assessing the plate at HOME clearance.
Hamilton instrument execution and Squid acquisition were not part of that handling run.

The earlier supervised plate run `20261111T145950Z_plate-workflow` completed through
the original facade, with operator assessment still pending. It predates these
dataset additions; no missing images or acquisitions are fabricated retrospectively.
