"""Read-only source ingestion. No application imports, network, or hardware commands."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

VERSION = 'cephla.training.v1'
ROOTS = [
    'operator_ui/logs/audit', 'operator_ui/logs/squid',
    'operator_ui/demonstrations', 'operator_ui/reports',
    'operator_ui/datasets/depth', 'operator_ui/depth_baselines',
    'operator_ui/captures', 'operator_ui/realsense_captures',
    'Pick and Hold', 'mujoco_sim/runs', 'newcam_images', 'reports',
]
ASSETS = {'.png', '.jpg', '.jpeg', '.npy', '.npz', '.ply', '.tif', '.tiff', '.mp4'}
TEXT = {'.json', '.jsonl', '.md'}
SECRET = re.compile(r'password|passwd|secret|api.?key|authorization|cookie|credential|^(?:access_|refresh_)?token$', re.I)
KEY_TEXT = re.compile(r'\b(?:sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~+/=-]+)', re.I)
NAMED_SECRET = re.compile(r'(?i)((?:api[_ -]?key|password|authorization)\s*[:=]\s*)[^\s,;]+')
MAX_RECORD = 64 * 1024 * 1024


def clean(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if SECRET.search(k) else clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str):
        return NAMED_SECRET.sub(r'\1[REDACTED]', KEY_TEXT.sub('[REDACTED]', value))
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def parse(raw):
    def reject(value):
        raise ValueError('Non-finite JSON value: ' + value)
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result): reject(value)
        return result
    return json.loads(raw, parse_constant=reject, parse_float=finite_float)


def identifier(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def epoch(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.timestamp() if dt.tzinfo else None
        except ValueError:
            pass
    return None


def timestamp(row):
    for key in ('server_timestamp', 'timestamp', 'at', 'received_at', 'requested_at', 'started_at', 'created_utc'):
        result = epoch(row.get(key))
        if result is not None:
            return result
    return None


def family(path):
    for root in ROOTS:
        if path.startswith(root + '/'):
            return root
    return 'reference'


def group(path):
    root = family(path)
    tail = path[len(root) + 1:].split('/')
    # Adjacent sessions must never be randomly split at the sample level.
    name = root + '/' + (tail[0] if len(tail) > 1 else 'ungrouped')
    return identifier(name), name


def evidence(row):
    """Literal evidence only: no success inferred from filenames or nested unrelated steps."""
    keys = ('ok', 'success', 'completed', 'status', 'state', 'error', 'errors',
            'reviewed', 'replay_approved', 'operator_confirmed', 'operator_accepted',
            'executable', 'simulation', 'stage_simulated', 'camera_simulated',
            'real_imaging_complete', 'completion_confirmed', 'calibration_complete')
    return {k: row[k] for k in keys if k in row}


def domain(path, row):
    if path.startswith('mujoco_sim/') or '/demo_output/' in path or '/ic_offline_' in path:
        return 'simulation_or_offline_fixture'
    if row.get('camera_simulated') is True and row.get('stage_simulated') is False:
        return 'real_stage_simulated_camera'
    if row.get('simulation') is True:
        return 'simulation_or_mixed_hardware'
    return 'unspecified_check_source'


def observation(row):
    robot = row.get('robot')
    if not isinstance(robot, dict) or not isinstance(robot.get('pose_mm'), dict):
        return None
    pose = robot['pose_mm']
    if not all(isinstance(pose.get(k), (int, float)) and not isinstance(pose.get(k), bool)
               and math.isfinite(pose[k]) for k in ('X', 'Y', 'Z', 'Rz')):
        return None
    return dict(time_s=timestamp(row), pose_mm_deg=pose,
                joints_native=robot.get('joints'), external_axes=robot.get('external_axes'),
                external_axes_units=robot.get('external_axes_units'),
                control_mode=robot.get('control_mode'), program_state=robot.get('program_state'),
                connected=robot.get('connected'), errors=robot.get('errors'),
                valid=row.get('valid', True) is not False and robot.get('ok') is not False
                      and robot.get('connected') is True and robot.get('errors') == [])


def asset_metadata(path):
    name = Path(path).name.lower()
    if name == 'prediction.npy':
        return dict(asset_kind='model_depth_prediction', supervision='model_prediction_not_ground_truth')
    if path.startswith('operator_ui/realsense_captures/') and name in ('depth_m.npy', 'depth_raw.png', 'cloud_m.ply'):
        return dict(asset_kind='depth_sensor_measurement', supervision='sensor_measurement_requires_registration_and_quality_checks')
    if path.startswith('mujoco_sim/') or '/demo_output/' in path:
        return dict(asset_kind='simulation_or_offline_fixture', supervision='synthetic_not_physical_ground_truth')
    if any(token in name for token in ('overlay', 'preview', 'matches', 'overview')):
        return dict(asset_kind='derived_visualization', supervision='visualization_not_ground_truth')
    return dict(asset_kind='image_or_array_check_source_metadata', supervision='unlabeled')


def classify_asset_index(snapshot):
    """Refresh only the derived asset taxonomy; source hashes and paths are unchanged."""
    path = snapshot / 'vision/assets.jsonl'
    if not path.exists(): return
    info = parse((snapshot / 'dataset.json').read_bytes())
    root = Path(info['source_root'])
    with (snapshot / 'source_manifest.jsonl').open(encoding='utf-8') as stream:
        manifests = {row['path']: row for row in map(parse, stream)}
    temp = path.with_suffix('.jsonl.tmp')
    count = 0
    with path.open(encoding='utf-8') as source, temp.open('w', encoding='utf-8') as dest:
        for line in source:
            row = parse(line)
            row.update(asset_metadata(row['source']))
            original = manifests[row['source']]
            try:
                current = (root / row['source']).stat()
                stable = (current.st_size == original['size_at_inventory'] and
                          current.st_mtime_ns == original['mtime_ns_at_inventory'] and
                          not original.get('changed_during_export'))
            except OSError:
                stable = False
            row['source_unchanged_at_finalization'] = stable
            row['eligibility'] = 'review_required' if stable else 'exclude_mutable_or_missing_source'
            dest.write(encode(row) + '\n'); count += 1
    temp.replace(path)
    print(encode(dict(asset_index_classified=count)), flush=True)


class Exporter:
    def __init__(self, root, output):
        self.root, self.output = root.resolve(), output.resolve()
        if self.output.exists():
            raise ValueError('Output already exists; use a new snapshot directory.')
        if self.output == self.root or self.output in self.root.parents:
            raise ValueError('Output must not contain the source repository.')
        self.output.mkdir(parents=True)
        self.handles, self.counts, self.groups = {}, Counter(), {}
        self.previous, self.last_poll = {}, {}
        self.hashes = {}
        self.progress_at = time.monotonic()
        self.started = datetime.now(timezone.utc).isoformat()

    def write(self, name, row):
        if name not in self.handles:
            path = self.output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            self.handles[name] = (gzip.open(path, 'wt', encoding='utf-8', compresslevel=1)
                                  if name.endswith('.gz') else path.open('w', encoding='utf-8'))
        self.handles[name].write(encode(clean(row)) + '\n')
        self.counts[name] += 1

    def quarantine(self, path, reason, line=None):
        self.write('quality/quarantine.jsonl', dict(source=path, line=line, reason=reason))
        # Never include malformed raw text: it may contain unredacted credentials.

    def record(self, path, value, line=None, offset=0):
        gid, gname = group(path)
        self.groups[gid] = gname
        rid = identifier(path + ':' + str(line or 0))
        base = dict(id=rid, group_id=gid, source=path, source_line=line,
                    source_byte_offset=offset, domain=domain(path, value if isinstance(value, dict) else {}))
        if not isinstance(value, dict):
            self.write('records/documents.jsonl.gz', dict(base, data=value))
            return
        if path.startswith('operator_ui/logs/audit/') and value.get('event') in ('http_request', 'http_response') and value.get('method') == 'GET':
            self.counts['excluded_get_poll_records'] += 1
            return
        ev = evidence(value)
        if ev:
            self.write('labels/evidence.jsonl.gz', dict(base, evidence=ev,
                interpretation='source_statement_not_independent_ground_truth',
                eligibility='review_required', split='unassigned'))
        obs = observation(value)
        if obs:
            if value.get('event') == 'robot_state':
                signature = encode({k: v for k, v in obs.items() if k != 'time_s'})
                if self.last_poll.get(path) == signature:
                    self.counts['excluded_identical_robot_polls'] += 1
                    return
                self.last_poll[path] = signature
            self.write('motion/observations.jsonl.gz', dict(base, **obs))
            if path.startswith('operator_ui/demonstrations/') and path.endswith('/samples.jsonl'):
                previous = self.previous.get(path)
                if previous and obs['valid'] and previous['valid'] and obs['time_s'] is not None and previous['time_s'] is not None:
                    dt = obs['time_s'] - previous['time_s']
                    if 0 < dt <= 1.0 and previous['source_line'] + 1 == line:
                        self.write('motion/transitions.jsonl.gz', dict(
                            id=identifier(previous['id'] + ':' + rid), group_id=gid,
                            observation_id=previous['id'], next_observation_id=rid,
                            dt_s=dt, state=previous['pose_mm_deg'], next_state=obs['pose_mm_deg'],
                            state_e1=previous.get('external_axes'), next_e1=obs.get('external_axes'),
                            state_external_axes_units=previous.get('external_axes_units'),
                            next_external_axes_units=obs.get('external_axes_units'),
                            target_semantics='next_observed_state_not_command',
                            eligibility='review_required', split='unassigned'))
                    else:
                        self.counts['excluded_transition_time_gaps'] += 1
                self.previous[path] = dict(obs, id=rid, source_line=line)
            if path.endswith('/samples.jsonl') or value.get('event') == 'robot_state':
                return
        target = 'agent_instruments/events.jsonl.gz' if line is not None else 'records/documents.jsonl.gz'
        self.write(target, dict(base, time_s=timestamp(value), data=value))

    def source(self, path, stat):
        rel = path.relative_to(self.root).as_posix()
        manifest = dict(path=rel, family=family(rel), size_at_inventory=stat.st_size,
                        mtime_ns_at_inventory=stat.st_mtime_ns)
        sha, consumed, lineno = hashlib.sha256(), 0, 0
        try:
            with path.open('rb') as stream:
                if path.suffix.lower() == '.jsonl':
                    while consumed < stat.st_size:
                        start = consumed
                        raw = stream.readline(min(MAX_RECORD + 1, stat.st_size - consumed))
                        if not raw:
                            break
                        sha.update(raw); consumed += len(raw); lineno += 1
                        if lineno % 10000 == 0 and time.monotonic() - self.progress_at > 20:
                            for handle in self.handles.values(): handle.flush()
                            print(encode(dict(stage='source_progress', source=rel, lines=lineno,
                                bytes_read=consumed, total_bytes=stat.st_size)), flush=True)
                            self.progress_at = time.monotonic()
                        if len(raw) > MAX_RECORD:
                            # Skip remainder of this oversized record without treating fragments as records.
                            while not raw.endswith(b'\n') and consumed < stat.st_size:
                                raw = stream.readline(min(MAX_RECORD, stat.st_size - consumed))
                                if not raw: break
                                sha.update(raw); consumed += len(raw)
                            self.quarantine(rel, 'record_exceeds_64MiB', lineno)
                            continue
                        if not raw.strip(): continue
                        try:
                            self.record(rel, parse(raw), lineno, start)
                        except (ValueError, TypeError, RecursionError) as error:
                            self.quarantine(rel, type(error).__name__ + ': invalid JSON record', lineno)
                else:
                    parts = []
                    while consumed < stat.st_size:
                        raw = stream.read(min(1024 * 1024, stat.st_size - consumed))
                        if not raw: break
                        sha.update(raw); consumed += len(raw)
                        if path.suffix.lower() in TEXT and stat.st_size <= MAX_RECORD:
                            parts.append(raw)
                    suffix = path.suffix.lower()
                    if suffix in ASSETS:
                        gid, gname = group(rel); self.groups[gid] = gname
                        self.write('vision/assets.jsonl', dict(source=rel, sha256=sha.hexdigest(),
                            size_bytes=consumed, group_id=gid, extension=suffix,
                            **asset_metadata(rel),
                            paired_metadata=(path.parent / 'metadata.json').relative_to(self.root).as_posix()
                            if (path.parent / 'metadata.json').exists() else None,
                            storage='source_reference_not_copied'))
                    elif stat.st_size > MAX_RECORD:
                        self.quarantine(rel, 'document_exceeds_64MiB')
                    else:
                        raw = b''.join(parts)
                        self.record(rel, parse(raw) if suffix == '.json' else dict(text=raw.decode('utf-8-sig')))
            final = path.stat()
            manifest.update(bytes_hashed=consumed, sha256=sha.hexdigest(),
                changed_during_export=(final.st_size != stat.st_size or final.st_mtime_ns != stat.st_mtime_ns),
                hash_scope='first_bytes_hashed_bytes', records_seen=lineno)
            if consumed != stat.st_size:
                self.quarantine(rel, 'source_shorter_than_inventory')
            elif not manifest['changed_during_export']:
                duplicate = self.hashes.get(sha.hexdigest())
                if duplicate:
                    manifest['duplicate_content_of'] = duplicate
                    self.write('quality/duplicate_sources.jsonl', dict(source=rel, identical_content_source=duplicate,
                        sha256=sha.hexdigest(), note='Keep together in evaluation splits; retained for provenance.'))
                else:
                    self.hashes[sha.hexdigest()] = rel
        except (OSError, ValueError, UnicodeError, RecursionError) as error:
            manifest['error'] = type(error).__name__
            self.quarantine(rel, type(error).__name__ + ': source_not_fully_exported')
        self.write('source_manifest.jsonl', manifest)
        self.counts['source_bytes_read'] += consumed

    def memory(self):
        path = self.root / 'operator_ui/logs/lacry_memory/memory.sqlite3'
        if not path.exists(): return
        # A single read transaction gives a consistent snapshot of the live database.
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            for table in ('memories', 'revisions'):
                for row in db.execute('SELECT * FROM ' + table):
                    self.write('memory/' + table + '.jsonl', dict(source=path.relative_to(self.root).as_posix(),
                        table=table, data=dict(row), eligibility='context_not_ground_truth'))

    def run(self):
        sources = []
        for name in ROOTS:
            root = self.root / name
            if not root.exists(): continue
            for path in root.rglob('*'):
                if self.output == path or self.output in path.parents: continue
                if path.is_symlink() or any(p in ('__pycache__', '.venv', 'tmp') for p in path.parts): continue
                if path.is_file() and path.suffix.lower() in TEXT | ASSETS:
                    sources.append((path, path.stat()))
        # Static profiles outside the recording directories provide provenance, never automatic acceptance.
        for pattern in ('*reference*.json', '*profile*.json', 'squid_protocols*.json*'):
            for path in (self.root / 'operator_ui').glob(pattern):
                if path.suffix in TEXT: sources.append((path, path.stat()))
        sources = sorted({p: s for p, s in sources}.items())
        print(encode(dict(stage='inventory', files=len(sources), bytes=sum(s.st_size for _, s in sources))), flush=True)
        last = time.monotonic()
        for index, (path, stat) in enumerate(sources, 1):
            self.source(path, stat)
            if time.monotonic() - last > 20:
                print(encode(dict(stage='export', files=index, total=len(sources), source_bytes_read=self.counts['source_bytes_read'])), flush=True)
                last = time.monotonic()
        self.memory()
        for gid, name in sorted(self.groups.items()):
            self.write('splits/groups.jsonl', dict(group_id=gid, source_group=name, split='unassigned',
                note='Keep related sessions and duplicated/replayed trajectories together; lineage review required before splitting.'))
        for handle in self.handles.values(): handle.close()
        summary = dict(schema=VERSION, created_utc=self.started, finished_utc=datetime.now(timezone.utc).isoformat(),
            source_root=str(self.root), status='structured_export_complete_review_required',
            counts=dict(self.counts), original_sources_modified=False,
            assets_copied=False, training_started=False, deployment_authorized=False,
            limitations=['No independent success labels inferred from filenames or ok=true.',
                'Transition targets are observed next states, not commanded actions.',
                'GET audit polling excluded; full originals retained.',
                'Timestamps are host/controller polling observations, not synchronized servo data.',
                'No train/validation/test split assigned before cross-session lineage review.',
                'Structured secret fields and common key patterns redacted; review before external sharing.'])
        (self.output / 'dataset.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        classify_asset_index(self.output)
        print(encode(summary), flush=True)
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--classify-assets', type=Path, help='Refresh an existing asset index without rebuilding the snapshot.')
    args = parser.parse_args()
    if args.classify_assets:
        classify_asset_index(args.classify_assets)
    else:
        output = args.output or args.root / 'training_data' / ('snapshot_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        Exporter(args.root, output).run()
