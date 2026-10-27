"""One-time evidence review of the Oct 20 refused Home startup; no hardware I/O.

Exact hashes bind this review to the two inspected records. Preserve originals,
failure statuses and logs; add proof of the specific pre-start refusal only.
"""
import hashlib
import json
from pathlib import Path
from home_attempts import HomeTravelNotStarted

ROOT = Path(__file__).resolve().parent
REVIEW = 'startup_refusal_1792501655449706400'
FILES = [
    ('reports/ik_home/1792501655449706400_a194efc4f79d4817b82ca7ce7b41337b.json',
     '7c1902abe32552c45c80c5becdcb967737fdff5ea15c5231bc3567340b924d1f'),
    ('reports/trajectory_smoothing/latest_button_runs/1792501655633024200_saved_home.json',
     '0533fa2a0d132726719fe590c846a5fff30655aefd5150dd333c4b3cde0b9100'),
]


def main():
    records = []
    originals = []
    for name, digest in FILES:
        data = (ROOT/name).read_bytes()
        record = json.loads(data)
        if record.get('home_startup_refusal', {}).get('review_id') == REVIEW:
            data = (ROOT/'reports/home_attempt_reviews'/REVIEW/Path(name).name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError('Record changed; this review cannot be applied: '+name)
        records.append(json.loads(data))
        originals.append(data)
    ik, route = records
    seq = ik['sequence']
    diagnostic = seq['result']['error']
    assert ik['status'] == 'failed_or_stopped' and seq['state'] == 'error'
    assert seq['result']['ok'] is False
    assert diagnostic.startswith('refusing to start: last gripper reading (E1 ')
    assert 'program start re-zeroes E1' in diagnostic
    assert len(seq['log']) == 2
    assert seq['log'][0]['msg'] == 'Preparing Auto motion for Home. Keep hands clear.'
    assert seq['log'][1]['msg'] == 'SEQUENCE ERROR: RuntimeError: '+diagnostic
    assert route['status'] == 'stopped_or_failed'
    assert route['target'] == ik['plan']['home']
    assert route['stages'] == ik['plan']['stages']
    assert route['prefix'] is None and route['connector'] is None
    evidence = HomeTravelNotStarted(diagnostic).evidence
    evidence.update(review_id=REVIEW, original_sha256=dict(FILES),
                    basis='Exact recorded refusal in _safe_start before prog_start; '
                          'Home executor exited its preparation phase before travel.')
    folder = ROOT/'reports/home_attempt_reviews'/REVIEW
    folder.mkdir(parents=True, exist_ok=True)
    for (name, _), data in zip(FILES, originals):
        backup = folder/Path(name).name
        if backup.exists() and backup.read_bytes() != data:
            raise RuntimeError('Review backup differs; stop for inspection.')
        if not backup.exists():
            backup.write_bytes(data)
    (folder/'review.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    for (name, _), record in zip(FILES, records):
        record['home_startup_refusal'] = evidence
        path = ROOT/name
        tmp = path.with_suffix('.review.tmp')
        tmp.write_text(json.dumps(record, indent=2), encoding='utf-8')
        tmp.replace(path)
    print(json.dumps(dict(review=str(folder/'review.json'), records_reviewed=len(records),
                          hardware_commands=0, original_failure_statuses_preserved=True)))


if __name__ == '__main__':
    main()
