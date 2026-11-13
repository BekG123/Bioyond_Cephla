"""The shared run dataset: one folder per run, one append-only event log.

runs/<utc>_<slug>/
    run.json        plan, versions, manifest hashes
    events.jsonl    one JSON object per line, flushed and synced per line
    ledger.json     where each plate is
    approval.json, attestation.json, human.jsonl   written only by HumanConsole
    frames/         stills before and after each step
    squid/ hamilton/ bioyond/   images and raw machine journals, hashed

Arrays and images stay in their own files (OME-Zarr, PNG). Facts go in
events.jsonl, and each event points at its files by relative path and sha256.
"""
from __future__ import annotations

from datetime import datetime, timezone
from .artifacts import FOLDERS, externalize, package
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import threading
import time

KINDS = ('status', 'command', 'gate', 'approval', 'result', 'anomaly', 'artifact', 'pause', 'resume')
SCHEMA_VERSION = 1


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


class EventLog:
    """Append-only. A crash can cost at most the line being written."""

    def __init__(self, path, run_id, clock=time.time):
        self.path, self.run_id, self.clock = Path(path), run_id, clock
        self.lock = threading.Lock()
        self.seq = 0
        if self.path.exists():
            raw = self.path.read_bytes()
            self.seq = max((e['seq'] for e in self.read()), default=0)
            if raw and not raw.endswith(b'\n'):
                # A torn last line stays as evidence; start the next event on its own line.
                with self.path.open('ab') as stream:
                    stream.write(b'\n')

    def emit(self, kind, *, machine=None, step=None, op=None, status=None, data=None, artifacts=()):
        if kind not in KINDS:
            raise ValueError(f'unknown event kind: {kind}')
        with self.lock:
            data, array_artifacts = externalize(data or {}, self.path.parent, machine, step)
            self.seq += 1
            event = dict(v=SCHEMA_VERSION, run=self.run_id, step=step, seq=self.seq, ts=iso(self.clock()),
                         mono_ns=time.monotonic_ns(), machine=machine, kind=kind, op=op, status=status,
                         data=data, artifacts=list(artifacts) + array_artifacts)
            line = json.dumps(event, allow_nan=False) + '\n'
            with self.path.open('ab') as stream:
                stream.write(line.encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            return event

    def read(self):
        """Every complete event. A torn or foreign line is skipped, never repaired."""
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_bytes().split(b'\n'):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and type(event.get('seq')) is int:
                events.append(event)
        return events


class NullEvents:
    """For a read made outside any run: nothing to log to."""
    def emit(self, kind, **fields):
        return dict(kind=kind, **fields)

    def read(self):
        return []


class RunFolder:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        record = json.loads((self.path / 'run.json').read_text(encoding='utf-8'))
        self.run_id = record['run_id']
        self.events = EventLog(self.path / 'events.jsonl', self.run_id, clock)

    @classmethod
    def create(cls, root, slug, plan, manifests, clock=time.time):
        from . import __version__
        now = clock()
        stamp = datetime.fromtimestamp(now, timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run_id = f"{stamp}_{re.sub(r'[^a-z0-9]+', '-', slug.lower()).strip('-') or 'run'}"
        path = Path(root) / run_id
        path.mkdir(parents=True, exist_ok=False)
        for name in ('frames', 'bioyond', 'hamilton', 'squid'):
            (path / name).mkdir()
        _write_json(path / 'run.json', dict(
            v=SCHEMA_VERSION, run_id=run_id, created=iso(now), plan=plan,
            manifest_hashes={m.id: m.sha256 for m in manifests.values()},
            versions=dict(labfacade=__version__, python=platform.python_version()),
            machine_folders={m: FOLDERS.get(m, m) for m in manifests}, approvals={}))
        _write_json(path / 'artifacts.json', dict(v=1, artifacts=[]))
        _write_json(path / 'ledger.json', dict(plates={
            plate: dict(location=location, step=None, ts=iso(now))
            for plate, location in (plan.get('plates') or {}).items()}))
        return cls(path, clock)

    @property
    def plan(self):
        """Read from disk every time: an edit after approval must be seen."""
        return json.loads((self.path / 'run.json').read_text(encoding='utf-8'))['plan']

    def read_json(self, name):
        try:
            return json.loads((self.path / name).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def write_json(self, name, data):
        _write_json(self.path / name, data)
        if name in ('approval.json', 'attestation.json'):
            record = self.read_json('run.json')
            record.setdefault('approvals', {})[name] = dict(path=name, sha256=sha256_file(self.path / name), record=data)
            _write_json(self.path / 'run.json', record)

    def artifact(self, path):
        path = Path(path)
        return dict(path=path.relative_to(self.path).as_posix(), sha256=sha256_file(path))

    def index_artifact(self, artifact, machine, step, detail):
        index = self.read_json('artifacts.json') or dict(v=1, artifacts=[])
        index['artifacts'].append(dict(machine=machine, step=step, **artifact, **detail))
        _write_json(self.path / 'artifacts.json', index)

    def collect(self, machine, source, step=None, *, ome=False):
        """Copy immutable step-scoped evidence; directories get a hashed file manifest."""
        source = Path(source)
        if machine == 'squid' and source.suffix.lower() in ('.tif', '.tiff'):
            raise ValueError('TIFF microscopy is not the run dataset format; preserve source and report mismatch.')
        if source.is_dir() and machine == 'squid' and (source.name.endswith('.zarr') or (source / 'zarr.json').exists()):
            ome = True
        artifact, detail = package(self.path, machine, step, source, ome=ome)
        self.index_artifact(artifact, machine, step, detail)
        self.events.emit('artifact', machine=machine, step=step, status='collected',
                         data=detail, artifacts=[artifact])
        return artifact


def _write_json(path, data):
    from .atomic_json import write_json
    write_json(path, data)
