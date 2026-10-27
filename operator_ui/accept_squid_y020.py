"""Apply the operator-accepted Y0.200 loading reference without moving hardware."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from squid_execution import SquidExecution, digest, at_position
from squid_bridge.selection_snapshot import layout_key
from trial_squid_y020 import arm_home_idle, EXPECTED, TARGET

ROOT = Path(__file__).resolve().parent
TRIAL = ROOT/'reports/squid_stage/y020_trial_20261024T160037Z'


def encode(value):
    return (json.dumps(value, indent=2, allow_nan=False)+'\n').encode()


def main():
    engine = SquidExecution(None)
    reference_path = ROOT/'squid_stage_reference.json'
    paths = [reference_path, engine.config, engine.locations_path, engine.selection_path]
    originals = {p: p.read_bytes() for p in paths}
    reference = json.loads(originals[reference_path])
    assert digest(reference) == EXPECTED, 'Reference changed since the accepted trial.'
    trial = json.loads((TRIAL/'trial.json').read_text())
    assert trial['status'] == 'passed_stage_only' and trial['target_mm'] == TARGET
    for measured in trial['measurements']:
        at_position(measured, TARGET)
    arm_home_idle()
    old_configured_hash = digest(engine.profile('current'))
    config = json.loads(originals[engine.config])
    acceptance = ('2026-10-24: operator confirmed the holder remains correctly positioned '
                  'for taught robot drop-off and pickup after the Y0.200 stage-only trial.')
    new_reference = deepcopy(reference)
    new_reference.update(
        dropoff=TARGET, stage_return_verified=True, accepted_for_robot_loading=True,
        operator_acceptance=acceptance,
        revision_authorization=trial['authorization'],
        successful_retry_report=str((TRIAL/'trial.json').relative_to(ROOT)),
        measured_retry_endpoint=trial['measurements'][-1],
        source='Operator-accepted inward Y revision after repeated near-home short stops.',
        validation='Three matching physical-stage readbacks within unchanged 0.020 mm per-axis tolerance. Robot remained at Home; holder placement accepted by operator.',
        previous_reference_sha256=EXPECTED)
    new_hash = digest(new_reference)
    config['profiles']['current'].update(loading_position=TARGET, loading_acceptance=acceptance)
    new_configured_hash = digest(dict(config['profiles']['current'], id='current'))
    rows = [json.loads(line) for line in originals[engine.locations_path].decode().splitlines()]
    records = []
    for row in rows:
        if row.get('event') == 'capture':
            assert digest(row['record']) == row['record_sha256'], 'Archive checksum mismatch.'
            records.append(row['record'])
    records.append(json.loads(originals[engine.selection_path]))
    latest = {}
    for record in sorted(records, key=lambda r:r['captured_at']):
        profile = record['plan']['profile']
        assert digest(profile) == record['plan']['profile_hash']
        assert hashlib.sha256(profile['captured_yaml'].encode()).hexdigest() == profile['params']['settings_sha256']
        latest[layout_key(profile['captured_yaml'])] = record
    now = time.time()
    migrated = []
    for key, record in latest.items():
        plan = record['plan']
        if plan['configured_hash'] != old_configured_hash or plan['profile'].get('loading_reference_hash') != EXPECTED:
            continue  # Never bless unrelated or stale records.
        updated = deepcopy(record)
        updated.update(captured_at=now, source='operator_accepted_loading_reference_migration',
                       original_captured_at=record['captured_at'], motion_authorized=False,
                       migration=dict(from_reference=EXPECTED, to_reference=new_hash,
                                      source_record_sha256=digest(record), acceptance=acceptance,
                                      imaging_coordinates_changed=False))
        p = updated['plan']
        p['profile'].update(loading_position=TARGET, loading_reference_hash=new_hash,
                            loading_acceptance=acceptance)
        p.update(loading_position=TARGET, configured_hash=new_configured_hash,
                 profile_hash=digest(p['profile']))
        assert p['profile']['captured_yaml'] == plan['profile']['captured_yaml']
        migrated.append(updated)
    assert migrated, 'No matching imaging history found.'
    new_rows = [dict(version=1, event='capture', at=now, motion_authorized=False,
                    record=r, record_sha256=digest(r)) for r in migrated]
    archive = originals[engine.locations_path]
    if archive and not archive.endswith(b'\n'):
        archive += b'\n'
    archive += ''.join(json.dumps(r, allow_nan=False)+'\n' for r in new_rows).encode()
    changes = {reference_path:encode(new_reference), engine.config:encode(config),
               engine.locations_path:archive, engine.selection_path:encode(migrated[-1])}
    backup = TRIAL/'accepted_reference_backup'
    backup.mkdir(exist_ok=False)
    for path, content in originals.items():
        (backup/path.name).write_bytes(content)
    arm_home_idle()
    assert all(path.read_bytes() == content for path, content in originals.items()), 'Concurrent edit; no update applied.'
    for path, content in changes.items():
        temporary = path.with_suffix(path.suffix+'.accept.tmp')
        temporary.write_bytes(content)
        temporary.replace(path)
    # Exercise the actual selection validator for every preserved layout.
    profile = engine.profile('current')
    assert digest(profile) == new_configured_hash
    profile['loading_reference_hash'] = new_hash
    for record in migrated:
        recovered = engine.saved_selection(profile, new_configured_hash, {},
                                           {'yaml':record['plan']['profile']['captured_yaml']})
        assert recovered['plan']['profile']['captured_yaml'] == record['plan']['profile']['captured_yaml']
    result = dict(status='accepted_and_integrated', at=now, acceptance=acceptance,
                  target_mm=TARGET, tolerance_mm=.02, reference_sha256=new_hash,
                  migrated_layouts=len(migrated), original_archive_preserved=True,
                  hardware_motion_started=False, backup=str(backup))
    (TRIAL/'acceptance.json').write_bytes(encode(result))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
