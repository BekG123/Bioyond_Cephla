"""One-run terminal review after the operator confirmed native completion.

Reads hardware only. Archives host ownership; does not manufacture a Pass or
retry calibration. The original missing-result outcome remains in the journal.
"""
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep, decoded


def main():
    root = Path(__file__).resolve().parents[1] / 'hamilton_api'
    request_id = 'c976de74e28143c18ad89eaec91d715a'
    marker = root / 'active.json'
    previous = json.loads(marker.read_text(encoding='utf-8'))
    assert previous['request_id'] == request_id
    assert previous['status'] == 'finished_unverified' and previous['native_finished']
    with urlopen('http://127.0.0.1:5002/state', timeout=8) as response:
        console = json.load(response)
    assert not console['sequence']['active']
    journal = root / (request_id + '.jsonl')
    rows = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
    terminal = []
    for row in rows:
        data = row.get('data')
        if row['kind'] != 'event' or not isinstance(data, dict):
            continue
        event = data.get('event')
        if not isinstance(event, dict):
            continue
        payload = decoded(event.get('data'))
        if isinstance(payload, dict) and payload.get('Source') == 'Unloads' and payload.get('Payload') == 'CleanupFinished':
            terminal.append(row)
    assert terminal, 'No native cleanup completion evidence.'
    assert not any(row['kind'] == 'request' and isinstance(row.get('data'), dict)
                   and row['data'].get('path') in ('calibration/abort', 'errors/runtime') for row in rows)
    adapter = HamiltonPrep()
    native = {path: adapter.call('GET', path) for path in (
        'instruments/global-run-state', 'protocol-run', 'service-software-api/is-parked',
        'service-software-api/has-tips', 'errors/check-for-pending-errors', 'calibration/channel-results')}
    assert native['instruments/global-run-state'] == 'Idle'
    assert not native['protocol-run']['isRunInProgress']
    assert native['service-software-api/is-parked'] is True
    assert native['service-software-api/has-tips'] is False
    assert not native['errors/check-for-pending-errors']
    folder = root / 'polling_20261027T004154Z_c5f6f459'
    record = dict(at=time.time(), request_id=request_id,
        operator_statement='Yes, I verify that Hamilton did finish the full calibration. Fix the handler incorrectly waiting bug',
        disposition='Operator confirmed completion; native cleanup and termination verified. Retire stale host ownership.',
        automatic_calibration_result_verified=False, native=native,
        cleanup_evidence=terminal, original_outcome=previous, controller_writes=0)
    destination = folder / 'operator_reviewed_terminal_active.json'
    assert not destination.exists()
    (folder / 'operator_cleanup_completion_review.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    with journal.open('a', encoding='utf-8') as out:
        out.write(json.dumps(dict(at=time.time(), kind='operator_terminal_review', data=record)) + '\n')
    marker.rename(destination)
    print(json.dumps(dict(request_id=request_id, operator_confirmed=True,
                          ownership_archived=True, controller_writes=0,
                          automatic_calibration_result_verified=False)))


if __name__ == '__main__':
    main()
