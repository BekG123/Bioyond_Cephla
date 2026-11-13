"""Persistent plate identity and rack records. No hardware or motion authority."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3


class PlateError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def default_path():
    # Shared by the operator checkout, clean-api checkout and scanner processes.
    return Path(os.environ.get('BIOYOND_PLATE_DB', str(Path.home()/'.bioyond'/'plates.sqlite3')))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def text(value, name, limit=2000, empty=False):
    if (not isinstance(value, str) or len(value) > limit or
            (not empty and not value.strip()) or any(ord(c) < 32 for c in value)):
        raise PlateError('Invalid '+name+'.')
    return value  # Never strip, case-fold or parse an ID as an integer.


class PlateRegistry:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS plates (
                    plate_id TEXT PRIMARY KEY, metadata TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 1, first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL, scan_count INTEGER NOT NULL DEFAULT 0,
                    assigned_slot TEXT UNIQUE, location TEXT NOT NULL DEFAULT 'unknown',
                    location_basis TEXT NOT NULL DEFAULT 'unknown');
                CREATE UNIQUE INDEX IF NOT EXISTS rack_occupancy ON plates(location)
                    WHERE location LIKE 'rack:%';
                CREATE TABLE IF NOT EXISTS plate_scans (
                    receipt_sha256 TEXT PRIMARY KEY, plate_id TEXT NOT NULL,
                    scanned_at TEXT NOT NULL, source TEXT NOT NULL, receipt TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plate_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, plate_id TEXT NOT NULL,
                    at TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rack_slots (slot TEXT PRIMARY KEY);
            ''')
            db.executemany('INSERT OR IGNORE INTO rack_slots VALUES (?)',
                           [(f'rack:1/slot:{i}',) for i in range(1, 6)])

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        except sqlite3.IntegrityError as error:
            raise PlateError('That slot is already assigned or occupied; refresh the inventory.', 409) from error
        finally:
            db.close()

    @staticmethod
    def _row(db, plate_id):
        text(plate_id, 'plate ID', 512)
        row = db.execute('SELECT * FROM plates WHERE plate_id=?', (plate_id,)).fetchone()
        if row is None:
            raise PlateError('No scanned plate with that exact ID.', 404)
        row = dict(row)
        row['metadata'] = json.loads(row['metadata'])
        return row

    @staticmethod
    def _event(db, plate_id, kind, source, data):
        db.execute('INSERT INTO plate_events(plate_id,at,kind,source,data) VALUES (?,?,?,?,?)',
                   (plate_id, stamp(), kind, text(source, 'source'), json.dumps(data, ensure_ascii=False)))

    def record_scan(self, receipt, source):
        """Accept only a complete, strictly decoded scanner frame; replay is idempotent."""
        if not isinstance(receipt, dict):
            raise PlateError('Invalid scanner receipt.')
        if receipt.get('result') != 'decoded':
            return None
        plate_id = text(receipt.get('barcode'), 'barcode', 512)
        try:
            raw_hex = receipt.get('response_hex')
            if raw_hex is None and receipt.get('response_complete') is True:
                raw_hex = ''.join(e['rx_hex'] for e in receipt.get('events', []) if 'rx_hex' in e)
            raw = bytes.fromhex(raw_hex)
            decoded = raw.split(b'\x04', 1)[0].decode('utf-8', errors='strict')
            at = receipt['at']
            parsed = datetime.fromisoformat(at)
            if parsed.utcoffset() is None:
                raise ValueError('Missing timezone')
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise PlateError('Invalid scanner frame or timestamp.') from error
        framed = receipt.get('framed') is True or receipt.get('response_complete') is True
        if not framed or b'\x04' not in raw or decoded != plate_id or decoded == 'NG':
            raise PlateError('A complete matching scanner frame is required.')
        # Ignore later registry status fields when deduplicating re-imported receipts.
        evidence = {k: v for k, v in receipt.items() if not k.startswith('plate_registry')}
        encoded = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
        sha = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        at = parsed.astimezone(timezone.utc).isoformat()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM plate_scans WHERE receipt_sha256=?', (sha,)).fetchone():
                return self._row(db, plate_id)
            db.execute('INSERT OR IGNORE INTO plates(plate_id,first_seen,last_seen) VALUES (?,?,?)',
                       (plate_id, at, at))
            db.execute('INSERT INTO plate_scans VALUES (?,?,?,?,?)', (sha, plate_id, at, text(source, 'source'), encoded))
            db.execute('UPDATE plates SET first_seen=min(first_seen,?),last_seen=max(last_seen,?),'
                       'scan_count=scan_count+1,revision=revision+1 WHERE plate_id=?', (at, at, plate_id))
            self._event(db, plate_id, 'scan', source, {'receipt_sha256': sha, 'scanned_at': at})
            # Scanning identifies a label; it does not prove its contents or location.
            return self._row(db, plate_id)

    def get(self, plate_id, history=False):
        with self.db() as db:
            row = self._row(db, plate_id)
            if history:
                row['history'] = [dict(r, data=json.loads(r['data'])) for r in db.execute(
                    'SELECT * FROM plate_events WHERE plate_id=? ORDER BY sequence DESC LIMIT 100', (plate_id,))]
            return row

    def search(self, query='', limit=20):
        text(query, 'query', 500, empty=True)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise PlateError('Limit must be 1 through 100.')
        with self.db() as db:
            rows = [dict(r, metadata=json.loads(r['metadata'])) for r in db.execute('SELECT * FROM plates ORDER BY last_seen DESC,plate_id')]
        exact = [r for r in rows if r['plate_id'] == query]
        tokens = [w for w in re.findall(r'\w+', query.casefold()) if w not in
                  {'plate', 'plates', 'the', 'a', 'is', 'where', 'what', 'with', 'for', 'of', 'my'}]
        if query and not exact:
            rows = [r for r in rows if tokens and any(w in (r['plate_id']+' '+json.dumps(r['metadata'], ensure_ascii=False)).casefold() for w in tokens)]
        elif exact:
            rows = exact
        return dict(plates=rows[:limit], total=len(rows), ambiguous=len(rows)>1, has_more=len(rows)>limit,
                    motion_authority=False, location_notice='Historical records; verify current physical state before handling.')

    def update(self, plate_id, revision, changes, source):
        if not isinstance(changes, dict) or not changes or set(changes)-{'contents','aliases','notes','experiment','plate_type'}:
            raise PlateError('Use contents, aliases, notes, experiment or plate_type.')
        for key, value in changes.items():
            if key == 'aliases':
                if not isinstance(value, list) or len(value)>20:
                    raise PlateError('Aliases must be a list of at most 20 names.')
                for alias in value:
                    text(alias, 'alias', 160)
            else:
                text(value, key, empty=True)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._checked(db, plate_id, revision)
            metadata = dict(row['metadata'], **changes)
            db.execute('UPDATE plates SET metadata=?, revision=revision+1 WHERE plate_id=?',
                       (json.dumps(metadata, ensure_ascii=False), plate_id))
            self._event(db, plate_id, 'researcher_annotation', source, {'before': row['metadata'], 'after': metadata})
            return self._row(db, plate_id)

    def _checked(self, db, plate_id, revision):
        row = self._row(db, plate_id)
        if type(revision) is not int or row['revision'] != revision:
            raise PlateError('Plate record changed; retrieve it again before saving.', 409)
        return row

    def _slot(self, db, slot, plate_id):
        text(slot, 'slot', 80)
        if not db.execute('SELECT 1 FROM rack_slots WHERE slot=?', (slot,)).fetchone():
            raise PlateError('Unknown rack slot. Read the rack inventory first.')
        if db.execute('SELECT 1 FROM plates WHERE plate_id<>? AND (assigned_slot=? OR location=?)',
                      (plate_id, slot, slot)).fetchone():
            raise PlateError('Rack slot is assigned to or occupied by another plate.', 409)

    def assign_slot(self, plate_id, revision, slot, source):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._checked(db, plate_id, revision)
            if slot is not None:
                self._slot(db, slot, plate_id)
            db.execute('UPDATE plates SET assigned_slot=?,revision=revision+1 WHERE plate_id=?', (slot, plate_id))
            self._event(db, plate_id, 'slot_assignment', source, {'before': row['assigned_slot'], 'after': slot})
            return self._row(db, plate_id)

    def report_location(self, plate_id, revision, location, source):
        text(location, 'location', 80)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._checked(db, plate_id, revision)
            if location not in ('unknown','HOME','Hamilton','Squid','gripper'):
                self._slot(db, location, plate_id)
            db.execute("UPDATE plates SET location=?,location_basis='researcher_report',revision=revision+1 WHERE plate_id=?", (location, plate_id))
            self._event(db, plate_id, 'reported_location', source, {'before': row['location'], 'after': location})
            return self._row(db, plate_id)

    def slots(self):
        with self.db() as db:
            return [dict(r, motion_commissioned=False) for r in db.execute('''
                SELECT s.slot, a.plate_id AS assigned_plate_id, p.plate_id AS reported_plate_id
                FROM rack_slots s LEFT JOIN plates a ON a.assigned_slot=s.slot
                LEFT JOIN plates p ON p.location=s.slot ORDER BY s.slot''')]

    def record_run(self, plate_id, run_id, outcome, source):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._row(db, plate_id)
            self._event(db, plate_id, 'instrument_run', source,
                        {'run_id': text(run_id, 'run ID', 200), 'outcome': text(outcome, 'outcome', 100)})
            # A compound workflow has no intermediate custody receipts here.
            # Invalidate old custody once a run attempted to handle this plate.
            if outcome not in ('refused', 'waiting'):
                db.execute("UPDATE plates SET location='unknown',location_basis='run_requires_reconciliation',revision=revision+1 WHERE plate_id=?", (plate_id,))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Import saved scanner receipts; no hardware calls.')
    parser.add_argument('--db')
    parser.add_argument('--import-scans', type=Path, required=True)
    args = parser.parse_args()
    registry = PlateRegistry(args.db)
    accepted, skipped, errors = 0, 0, []
    for path in sorted(args.import_scans.glob('scan_*.json')):
        try:
            row = registry.record_scan(json.loads(path.read_text(encoding='utf-8')), str(path.resolve()))
            accepted += row is not None
            skipped += row is None
        except (PlateError, OSError, ValueError) as error:
            errors.append({'file': str(path), 'error': str(error)})
    print(json.dumps(dict(decoded_receipts_processed=accepted, skipped=skipped, errors=errors,
                         inventory=registry.search(), database=str(registry.path)), ensure_ascii=True, indent=2))
    raise SystemExit(bool(errors))
