"""Timeouts, stale readings and crashes. Unknown is never treated as fine."""
import json

import jsonschema

from labfacade.events import EventLog
from conftest import REPO, kinds


def test_timeout_means_unknown_and_is_never_resent(lab):
    fake = lab.fakes['hamilton_prep']
    fake.behaviors['park'] = dict(hang=1.0)
    run, console = lab.run()
    result = lab.facade.run_step(run, 's04')
    assert (result['outcome'], result['code']) == ('unknown', 'timeout')
    assert len(fake.commands) == 1
    assert [e['status'] for e in kinds(run, 'anomaly')] == ['timeout']
    assert [e['data']['phase'] for e in kinds(run, 'status') if 'phase' in e['data']] == ['before', 'requery']
    assert lab.facade.run_step(run, 's04')['code'] == 'run_paused'
    console.resume('bek', 'inspected: channels parked')
    assert lab.facade.run_step(run, 's04')['code'] == 'already_attempted'
    assert len(fake.commands) == 1                            # sent exactly once, ever


def test_timeout_during_a_transfer_marks_the_plate_unknown(lab):
    lab.fakes['bioyond_s4'].behaviors['place_plate'] = dict(hang=1.0)
    run, _ = lab.run()
    assert lab.facade.run_step(run, 's02')['outcome'] == 'unknown'
    assert run.read_json('ledger.json')['plates']['P1']['location'] == 'unknown'


def test_backend_error_stops_the_run(lab):
    lab.fakes['squid'].behaviors['run_imaging'] = dict(raises='stage fault')
    run, _ = lab.run()
    result = lab.facade.run_step(run, 's03')
    assert (result['outcome'], result['code']) == ('failed', 'error') and 'stage fault' in result['reason']
    assert lab.facade.run_step(run, 's04')['code'] == 'run_paused'


def test_stale_missing_or_contradictory_status_is_unknown(lab):
    fake = lab.fakes['squid']
    assert lab.facade.status('squid')['state'] == 'idle'
    fake.status_age_s = 11
    assert lab.facade.status('squid')['state'] == 'unknown' and 'old' in lab.facade.status('squid')['detail']
    fake.status_age_s = 0
    fake.sources = {'counter': 'idle', 'encoder': 'busy'}
    assert lab.facade.status('squid')['state'] == 'unknown'
    fake.sources = {}
    fake.state = 'probably fine'
    assert lab.facade.status('squid')['state'] == 'unknown'
    fake.state = 'idle'
    fake.status_fails = True
    status = lab.facade.status('squid')
    assert status['state'] == 'unknown' and set(status) == {'machine', 'state', 'detail', 'ts_utc', 'source'}


def test_unknown_state_before_a_step_pauses_without_sending(lab):
    lab.fakes['squid'].status_age_s = 60
    run, _ = lab.run()
    result = lab.facade.run_step(run, 's01')
    assert (result['outcome'], result['code']) == ('paused', 'state_unknown')
    assert lab.sent('squid') == []


def test_event_log_survives_a_crash_mid_line(tmp_path):
    path = tmp_path / 'events.jsonl'
    log = EventLog(path, 'r1')
    for n in range(3):
        log.emit('status', machine='squid', status='idle', data=dict(n=n))
    intact = path.read_bytes()
    with path.open('ab') as stream:                           # the process died while writing line 4
        stream.write(b'{"v": 1, "run": "r1", "seq": 4, "kind": "comm')
    torn = path.read_bytes()

    reopened = EventLog(path, 'r1')
    assert [e['seq'] for e in reopened.read()] == [1, 2, 3]
    reopened.emit('result', machine='squid', status='completed')
    after = path.read_bytes()
    assert after.startswith(torn) and torn.startswith(intact)  # nothing already written was changed
    assert [e['seq'] for e in reopened.read()] == [1, 2, 3, 4]
    assert reopened.read()[-1]['kind'] == 'result'


def test_events_match_the_published_schema(lab):
    run, console = lab.run()
    lab.fakes['squid'].behaviors['run_imaging'] = dict(raises='stage fault')
    for step in ('s01', 's02', 's03'):
        lab.facade.run_step(run, step)
    console.resume('bek', 'inspected')
    lab.facade.abort('squid', run)
    schema = json.loads((REPO / 'labfacade' / 'schemas' / 'event.schema.json').read_text())
    events = run.events.read()
    for event in events:
        jsonschema.validate(event, schema)
    assert [e['seq'] for e in events] == list(range(1, len(events) + 1))
    assert {e['kind'] for e in events} >= {'approval', 'status', 'gate', 'command', 'result', 'anomaly',
                                           'artifact', 'pause', 'resume'}
    for event in events:
        for artifact in event['artifacts']:
            assert (run.path / artifact['path']).exists() and '\\' not in artifact['path']


def test_raw_journals_are_copied_in_and_hashed(lab, tmp_path):
    run, _ = lab.run()
    journal = tmp_path / 'dcg_tool_return.jsonl'
    journal.write_text('{"kind": "park_result"}\n')
    artifact = run.collect('hamilton_prep', journal, step='s04')
    assert artifact['path'].startswith('hamilton/s04/') and artifact['path'].endswith('/dcg_tool_return.jsonl') and len(artifact['sha256']) == 64
    assert kinds(run, 'artifact')[-1]['artifacts'] == [artifact]
