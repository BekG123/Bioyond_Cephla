"""Preserve a terminal demonstration as a versioned path; offline, never replay."""
import argparse
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def export(folder, parent, backup, since):
    folder, parent, backup = map(Path, (folder, parent, backup))
    status = json.loads((folder / 'status.json').read_text())
    if status['recording']:
        raise ValueError('Stop recording before exporting.')
    destination = folder / 'descent_path_v2.json'
    if destination.exists():
        raise ValueError('Version already exists; preserve it.')
    raw = (folder / 'samples.jsonl').read_bytes()
    dedicated = [json.loads(line) for line in raw.splitlines()]
    parent_raw = parent.read_bytes()
    baseline = json.loads(parent_raw)
    # Snapshot only complete lines within the requested startup window.
    recovered = []
    with backup.open('rb') as stream:
        for line in stream:
            if not line.endswith(b'\n'):
                break
            row = json.loads(line)
            if since <= row['requested_at'] < dedicated[0]['requested_at']:
                recovered.append((line, row))
            if row['requested_at'] >= dedicated[0]['requested_at']:
                break
    if not recovered:
        raise ValueError('No startup backup samples in requested window.')
    samples = [row for _, row in recovered] + dedicated
    axes = ('X', 'Y', 'Z', 'Rz')
    valid = [r for r in samples if r.get('valid') and r.get('robot', {}).get('pose_mm')]
    tail = samples[-10:]
    if len(tail) < 10 or not all(r in valid for r in tail):
        raise ValueError('Final pose unavailable.')
    end = {k: statistics.median(r['robot']['pose_mm'][k] for r in tail) for k in axes}
    start = {k: baseline['plan']['end'][k] for k in axes}
    wrap = lambda a: (a + 180) % 360 - 180
    offset = {k: end[k] - start[k] for k in axes}
    offset['Rz'] = wrap(offset['Rz'])
    spans = {k: max(r['robot']['pose_mm'][k] for r in tail) - min(r['robot']['pose_mm'][k] for r in tail) for k in axes}
    e1 = [r['robot']['external_axes']['E1'] for r in valid if 'E1' in r['robot'].get('external_axes', {})]
    gaps = [(datetime.fromisoformat(b['requested_at']) - datetime.fromisoformat(a['requested_at'])).total_seconds() for a, b in zip(samples, samples[1:])]
    restored_raw = b''.join(line for line, _ in recovered)
    reasons = ['Terminal correction includes XY/yaw; current Lua descent supports pure Z only.',
               'Observed gripper motion is retained as evidence, not a replay command or force label.',
               'No corrected-path IK, swept-clearance check, or automatic hardware trial performed.']
    if max(e1) > 28.05:
        reasons.append('Hand-guided E1 feedback exceeded configured 28 mm command limit; do not replay raw E1 values.')
    if len(valid) != len(samples):
        reasons.append('Invalid samples present.')
    if max(spans.values()) > .1:
        reasons.append('Endpoint not stationary within 0.1 mm/degree.')
    path = dict(schema='cephla.descent-path.v2', created_at=datetime.now(timezone.utc).isoformat(),
        status='recorded_correction_pending_replay_validation', replay_approved=False, active_for_execution=False,
        parent=dict(path=str(parent), sha256=sha(parent_raw), run_id=baseline['run_id']),
        sources=dict(dedicated_sha256=sha(raw), startup_backup_sha256=sha(restored_raw),
                     backup_path=str(backup), backup_first_index=recovered[0][1]['index'],
                     backup_last_index=recovered[-1][1]['index']),
        feedback='Operator demonstrated an adjustment to final descent and requested adding it to the learned path.',
        coordinate_frame='Robot base; offsets describe this plate/alignment only, not a calibrated transferable tool-frame correction.',
        original_endpoint=start, corrected_endpoint=end, endpoint_offset=offset,
        endpoint_xy_shift_mm=math.hypot(offset['X'], offset['Y']),
        final_window_span=spans, dedicated_samples=len(dedicated), recovered_samples=len(recovered),
        invalid_samples=len(samples)-len(valid), maximum_sample_gap_s=max(gaps),
        observed_e1_range_mm=[min(e1), max(e1)], observed_final_e1_mm=statistics.median(e1[-10:]),
        replay_blockers=reasons,
        phases=[dict(name='tested_vertical_descent', executor='lua_descent', protocol=baseline['protocol'],
                     plan=baseline['plan']),
                dict(name='manual_terminal_correction', executable=False, samples=[
                    dict(at=r['requested_at'], source='startup_backup' if i < len(recovered) else 'dedicated',
                         source_index=r['index'], valid=r.get('valid'), pose_mm=r.get('robot', {}).get('pose_mm'),
                         joints=r.get('robot', {}).get('joints'),
                         observed_external_axes=r.get('robot', {}).get('external_axes'),
                         errors=r.get('robot', {}).get('errors')) for i, r in enumerate(samples)])])
    (folder / 'startup_backup.jsonl').write_bytes(restored_raw)
    (folder / 'teaching_context.json').write_text(json.dumps(dict(
        user_request=path['feedback'], backup_recovered=True,
        note='Dedicated stream started after the movement; continuous logger supplies its startup segment.',
        parent=path['parent'], prior_grip='Uneven jaw contact; left jaw gap reported. Claw reopened before correction.',
        force_labels_available=False), indent=2), encoding='utf-8')
    destination.write_text(json.dumps(path, indent=2, allow_nan=False), encoding='utf-8')
    assert sha((folder / 'samples.jsonl').read_bytes()) == path['sources']['dedicated_sha256']
    assert sha(parent.read_bytes()) == path['parent']['sha256']
    assert json.loads(destination.read_text())['phases'][0]['plan'] == baseline['plan']
    return {k: v for k, v in path.items() if k not in ('phases',)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    parser.add_argument('--parent', required=True)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--since', required=True, help='Inclusive ISO UTC recording timestamp')
    args = parser.parse_args()
    print(json.dumps(export(args.folder, args.parent, args.backup, args.since), indent=2))
