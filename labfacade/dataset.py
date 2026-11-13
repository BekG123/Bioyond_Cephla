"""Dataset integrations around existing executors; no motion or control commands."""
from __future__ import annotations

from io import BytesIO
import json
import os
import threading
from pathlib import Path
from urllib.request import build_opener, ProxyHandler, Request

from .artifacts import component, digest, FOLDERS, externalize
from .events import iso
from .squid_format import configured_saving_format


class ConsoleFrame:
    """A cell inspection image from the existing camera owner, not a microscope acquisition."""
    def __init__(self, base='http://127.0.0.1:5002'):
        self.url = base.rstrip('/') + '/frame'

    def __call__(self, path):
        from PIL import Image
        opener = build_opener(ProxyHandler({}))
        with opener.open(Request(self.url, headers={'Cache-Control': 'no-cache'}), timeout=5) as response:
            if response.headers.get('X-Error'):
                raise RuntimeError('Camera returned stale/unavailable frame: ' + response.headers['X-Error'])
            payload = response.read(32 * 1024 * 1024 + 1)
        if len(payload) > 32 * 1024 * 1024:
            raise ValueError('Camera response exceeds 32 MiB.')
        with Image.open(BytesIO(payload)) as frame:
            frame.load()
            frame.save(path, format='PNG')
        return True


class DatasetSources:
    """Explicit local handoff for journals and finalized acquisitions.

    No directory-wide latest-file guessing. An output must be named by the owner
    or by a receipt. Sources are only read; active.json and lock files are excluded.
    """
    def __init__(self, frame=None, journals=(), images=(), software_dir=None, active_config=None, acquisitions=()):
        self.frame = frame
        self.journals = tuple(Path(p) for p in journals)
        self.images = tuple(Path(p) for p in images)
        self.software_dir = Path(software_dir) if software_dir else None
        self.active_config = Path(active_config) if active_config else None
        self.acquisitions = tuple(acquisitions)

    def report(self):
        if self.software_dir is None:
            return None
        return configured_saving_format(self.software_dir, active_config=self.active_config)


class RawJournal:
    """Durable transport facts, using the facade's clock; one journal per dispatch."""
    def __init__(self, run, machine, step):
        from uuid import uuid4
        self.run, self.machine, self.step = run, machine, step
        self.path = run.path / FOLDERS.get(machine, component(machine)) / component(step or 'run') / uuid4().hex / 'transport.jsonl'
        self.path.parent.mkdir(parents=True)
        self.lock = threading.Lock()
        self.closed = False

    def __call__(self, kind, data):
        with self.lock:
            if self.closed:
                return  # a late result cannot mutate evidence already hashed after timeout
            facts, artifacts = externalize(data, self.run.path, self.machine, self.step)
            record = dict(run=self.run.run_id, step=self.step, machine=self.machine, ts=iso(self.run.clock()),
                          kind=kind, data=facts, artifacts=artifacts)
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, allow_nan=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

    def finish(self):
        with self.lock:
            self.closed = True
            if not self.path.exists():
                return None
            artifact = self.run.artifact(self.path)
            self.run.index_artifact(artifact, self.machine, self.step, dict(type='transport_journal'))
            self.run.events.emit('artifact', machine=self.machine, step=self.step, status='transport_journal', artifacts=[artifact])
            return artifact

def squid_sources(frame=None, software_dir=None, active_config=None, journals=(), images=()):
    software = software_dir or os.environ.get('SQUID_SOFTWARE_DIR') or Path.home() / 'Desktop/squid-latest/software'
    return DatasetSources(frame, journals, images, software, active_config)


def inspection_quality(path):
    """Conservative content warning, not proof that the plate is visible or secure."""
    import numpy as np
    from PIL import Image
    with Image.open(path) as image:
        width, height = image.size
        image = image.convert('L')
        image.thumbnail((256, 256))
        pixels = np.asarray(image, dtype=float)
    edges = np.concatenate((np.abs(np.diff(pixels, axis=0)).ravel(),
                            np.abs(np.diff(pixels, axis=1)).ravel()))
    edge_fraction = float(np.mean(edges >= 8)) if edges.size else 0.0
    reasons = []
    if min(width, height) < 32:
        reasons.append('image_too_small')
    if edge_fraction < .001:
        reasons.append('very_low_detail')
    return dict(policy='inspection_detail_v1', status='suspect' if reasons else 'no_issue_detected',
                reasons=reasons, width=width, height=height, edge_fraction=edge_fraction,
                edge_threshold=8, minimum_edge_fraction=.001,
                scope='image-content heuristic only; does not verify plate visibility or physical state')


def bioyond_receipt_roots(checkout):
    checkout = Path(checkout)
    return [checkout / 'operator_ui/reports', checkout / 'reports',
            checkout / 'operator_ui/demonstrations/pickup_holder',
            checkout / 'operator_ui/demonstrations/reference_grip']


def collect_receipts(run, machine, step, initial, roots, limit=256, *, reuse_existing=False):
    """Copy a referenced evidence graph, preserving raw bytes and a portable index.

    Only explicit known path fields under allowed roots are followed. Absolute paths
    in raw originals stay untouched; artifacts.json maps each source to its copy.
    """
    roots = [Path(p).resolve() for p in roots]
    pending = [Path(p) for p in initial]
    visited, artifacts = set(), []
    existing = {str(Path(a['original']).resolve()): a for a in (run.read_json('artifacts.json') or {}).get('artifacts', [])
                if a.get('original') and a.get('type') == 'file' and a.get('machine') == machine and a.get('step') == step}
    fields = {'record', 'source', 'calibration_record', 'starting_receipt', 'final_receipt',
              'previous_release_receipt', 'receipt', 'journal', 'journal_path', 'output_path',
              'frame', 'frame_path', 'image_path', 'clearance_record', 'grip_record',
              'descent_record', 'alignment_record', 'home_squid_trial'}

    def references(value, folder):
        if isinstance(value, dict):
            for key, val in value.items():
                if key in fields and isinstance(val, str) and val:
                    p = Path(val)
                    # `source` also describes provenance (button, native_motion_status,
                    # etc.). Only path-shaped values denote evidence; missing paths
                    # still produce an anomaly rather than being silently ignored.
                    if key == 'source' and not (p.is_absolute() or '/' in val or '\\' in val or p.suffix):
                        continue
                    yield p if p.is_absolute() else folder / p
                elif isinstance(val, (dict, list)):
                    yield from references(val, folder)
        elif isinstance(value, list):
            for child in value:
                yield from references(child, folder)

    while pending:
        path = pending.pop(0).resolve()
        if path in visited:
            continue
        visited.add(path)
        if len(visited) > limit:
            run.events.emit('anomaly', machine=machine, step=step, status='evidence_limit', data=dict(limit=limit))
            break
        if not any(path.is_relative_to(root) for root in roots) or path.name == 'active.json' or path.suffix == '.lock':
            run.events.emit('anomaly', machine=machine, step=step, status='evidence_path_rejected', data=dict(source=str(path)))
            continue
        try:
            ome = path.is_dir() and (path.name.endswith('.zarr') or (path / 'zarr.json').exists())
            prior = existing.get(str(path)) if reuse_existing else None
            if prior:
                archived = run.path / prior['path']
                if digest(path) != prior['sha256'] or digest(archived) != prior['sha256']:
                    raise ValueError('Previously collected receipt changed; historical evidence cannot be replaced.')
                artifacts.append({k: prior[k] for k in ('path', 'sha256')})
            else:
                artifact = run.collect(machine, path, step, ome=ome)
                artifacts.append(artifact)
                archived = run.path / artifact['path']
            # Follow the exact snapshot just hashed, using the original parent for
            # relative references. Never parse a potentially changing source again.
            if path.suffix == '.json' and archived.stat().st_size <= 32 * 1024 * 1024:
                pending.extend(references(json.loads(archived.read_text(encoding='utf-8-sig')), path.parent))
            elif path.suffix == '.jsonl' and archived.stat().st_size <= 32 * 1024 * 1024:
                for line in archived.read_text(encoding='utf-8-sig').splitlines():
                    try:
                        pending.extend(references(json.loads(line), path.parent))
                    except ValueError:
                        continue  # raw torn journal is preserved, never repaired
        except Exception as error:
            run.events.emit('anomaly', machine=machine, step=step, status='evidence_not_collected',
                            data=dict(source=str(path), error=str(error)))
    return artifacts


class StepDataset:
    def __init__(self, run, machine, step, backend, operation):
        self.run, self.machine, self.step = run, machine, step
        self.backend, self.operation = backend, operation
        self.sources = getattr(backend, 'dataset_sources', DatasetSources())
        self.artifacts = []
        self.phase_number = 0
        self.phase = None
        self.cycle = None
        self.journal = None

    def progress(self, line):
        if not isinstance(line, dict):
            line = dict(text=str(line))
        if 'cycle' in line:
            self.cycle = line['cycle']
        label = line.get('phase')
        if label and (label != self.phase or line.get('status') == 'starting'):
            self.phase_number += 1
            self.phase = label
        plates = self.run.plan.get('plates', {})
        return dict(phase='progress', line=line, phase_id=f'{self.step}.p{self.phase_number:03d}',
                    phase_label=self.phase, cycle=self.cycle, plate_ids=list(plates))

    def emit(self, kind, status, **data):
        self.run.events.emit(kind, machine=self.machine, step=self.step, op=self.operation, status=status, data=data)

    def frame(self, when):
        capture = self.sources.frame or getattr(self.backend, 'capture_frame', None)
        if not capture:
            self.emit('anomaly', 'frame_unavailable', when=when, reason='No frame source configured.')
            return
        from uuid import uuid4
        path = self.run.path / 'frames' / component(self.step or 'run') / f'{when}_{uuid4().hex}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if not capture(path) or not path.is_file():
                raise RuntimeError('Frame source did not produce an image.')
            from PIL import Image
            with Image.open(path) as img:
                if img.format != 'PNG':
                    raise ValueError('Inspection frame is not PNG.')
                img.verify()
            quality = inspection_quality(path)
            artifact = self.run.artifact(path)
            self.artifacts.append(artifact)
            self.run.index_artifact(artifact, self.machine, self.step, dict(type='inspection_frame', when=when,
                                    source=getattr(capture, 'url', 'backend callback'), quality=quality))
            self.run.events.emit('artifact', machine=self.machine, step=self.step, op=self.operation,
                                 status=when, artifacts=[artifact], data=dict(source=getattr(capture, 'url', 'backend callback'), quality=quality))
            if quality['status'] == 'suspect':
                self.emit('anomaly', 'frame_quality_suspect', when=when, path=artifact['path'], quality=quality)
        except Exception as error:
            self.emit('anomaly', 'frame_failed', when=when, error=str(error))

    def before(self):
        self.start_sequence = self.run.events.seq
        self.journal = RawJournal(self.run, self.machine, self.step)
        self.backend.dataset_journal = self.journal
        self.journal('dispatch_context', dict(operation=self.operation))
        # A configuration report is evidence, never proof of the live runtime format.
        reporters = [(self.machine, self.sources)]
        embedded = getattr(self.backend, 'squid', None)
        if embedded is not None and hasattr(embedded, 'dataset_sources'):
            reporters.append(('squid', embedded.dataset_sources))
        for machine, sources in reporters:
            try:
                report = sources.report()
                if report:
                    self.run.events.emit('anomaly' if report['warning'] else 'status', machine=machine,
                                         step=self.step, status='saving_format', data=report)
            except Exception as error:
                self.emit('anomaly', 'saving_format_unavailable', error=str(error))
        self.frame('before')

    def after(self):
        if self.journal:
            artifact = self.journal.finish()
            if artifact:
                self.artifacts.append(artifact)
        self.frame('after')
        backend = self.backend
        try:
            if hasattr(backend, 'collect_dataset'):
                self.artifacts.extend(backend.collect_dataset(self.run, self.step, self.operation))
            else:
                for path in backend.evidence(self.operation) if hasattr(backend, 'evidence') else ():
                    self.artifacts.append(self.run.collect(self.machine, path, self.step))
        except Exception as error:
            self.emit('anomaly', 'evidence_not_collected', error=str(error))
        for path in self.sources.journals:
            try:
                if path.name == 'active.json' or path.suffix == '.lock':
                    raise ValueError('Ownership markers and lock files are not collected.')
                self.artifacts.append(self.run.collect(self.machine, path, self.step))
            except Exception as error:
                self.emit('anomaly', 'evidence_not_collected', source=str(path), error=str(error))
        for path in self.sources.images:
            try:
                self.artifacts.append(self.run.collect(self.machine, path, self.step, ome=True))
            except Exception as error:
                self.emit('anomaly', 'imaging_dataset_rejected', source=str(path), error=str(error))
        for handoff in self.sources.acquisitions:
            try:
                self.artifacts.extend(collect_acquisition(self.run, self.step, **handoff))
            except Exception as error:
                self.emit('anomaly', 'imaging_dataset_rejected', error=str(error))
        gaps = [dict(status=e['status'], detail=e['data']) for e in self.run.events.read()
                if e['seq'] > self.start_sequence and e['step'] == self.step and e['kind'] == 'anomaly'
                and e['status'] in ('frame_unavailable', 'frame_failed', 'frame_quality_suspect', 'evidence_not_collected',
                                    'evidence_path_rejected', 'evidence_limit', 'imaging_dataset_rejected',
                                    'saving_format_unavailable')]
        summary = self.run.read_json('dataset.json') or dict(v=1, steps={})
        summary['steps'][self.step] = dict(machine=self.machine, operation=self.operation,
            artifact_count=len(self.artifacts), complete=not gaps, gaps=gaps)
        self.run.write_json('dataset.json', summary)
        self.emit('status', 'dataset_collected', artifact_count=len(self.artifacts), complete=not gaps, gaps=gaps)
        return [a['path'] for a in self.artifacts]


def collect_acquisition(run, step, receipt, expected_run_id, output_roots):
    """Ingest one explicitly bound, finalized native Squid acquisition. Files only.

    This does not launch imaging or infer ownership from whichever run is newest.
    TIFF and incomplete/6D stores are rejected, not converted or relabelled.
    """
    from .artifacts import inventory, validate_ome
    from .events import sha256_file
    if not any(s['id'] == step for s in run.plan['steps']):
        raise ValueError('Unknown facade step.')
    receipt = Path(receipt).resolve(strict=True)
    fingerprint = sha256_file(receipt)
    data = json.loads(receipt.read_text(encoding='utf-8-sig'))
    if not expected_run_id or data.get('run_id') != expected_run_id or data.get('schema_version') != 1:
        raise ValueError('Acquisition receipt identity/schema mismatch.')
    if data.get('status') != 'completed' or not isinstance(data.get('ended_at'), (int, float)):
        raise ValueError('Acquisition has no completed receipt.')
    output = Path(data['output_path']).resolve(strict=True)
    if not any(output.is_relative_to(Path(root).resolve()) for root in output_roots):
        raise ValueError('Acquisition output outside configured roots.')
    inventory(output)  # checks symlinks before directory discovery
    candidates = [output] if output.name.endswith('.zarr') else sorted(output.rglob('*.zarr'))
    stores = [p for p in candidates if not any(parent in candidates for parent in p.parents)]
    if not stores:
        raise ValueError('No OME-Zarr output; TIFF/individual images are not accepted as OME.')
    for path in stores:
        validate_ome(path)
    config = data.get('config_path')
    if config and Path(config).is_file():
        report = configured_saving_format(Path(config).parent, active_config=config)
        run.events.emit('anomaly' if report['warning'] else 'status', machine='squid', step=step,
                        status='saving_format', data=report)
    artifacts = [run.collect('squid', path, step, ome=True) for path in stores]
    if sha256_file(receipt) != fingerprint:
        raise ValueError('Acquisition receipt changed during collection.')
    artifacts.append(run.collect('squid', receipt, step))
    run.events.emit('result', machine='squid', step=step, op='collect_acquisition', status='dataset_verified',
                    data=dict(acquisition_run_id=expected_run_id, experiment_id=data.get('experiment_id'),
                              plate_ids=list(run.plan.get('plates', {})), dataset_count=len(stores),
                              hardware_completion='receipt-reported; no new hardware check'), artifacts=artifacts)
    return artifacts
