"""Export a stopped hand-guided return recording; never execute robot commands."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from autonomy import TransferError, check_path, wrap


def review(folder):
    folder = Path(folder)
    root = Path(__file__).resolve().parent
    status = json.loads((folder / 'status.json').read_text())
    if status['recording']:
        raise ValueError('Stop the dedicated recorder before reviewing the return path.')
    raw = (folder / 'samples.jsonl').read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    if len(rows) < 2 or len(rows) != status['samples'] or [s['index'] for s in rows] != list(range(len(rows))):
        raise ValueError('Recording is empty or has missing/out-of-order samples.')
    context = json.loads((folder / 'return_home_context.json').read_text(encoding='utf-8-sig'))
    params = json.loads((root / 'robot_params.json').read_text())
    workspace = json.loads((root / 'envelope.json').read_text())
    trajectory = []
    failures = []
    kinematic_failures = []
    for row in rows:
        robot = row.get('robot', {})
        trajectory.append(dict(index=row['index'],elapsed_s=row['elapsed_s'],at=row['received_at'],
            valid=row['valid'],pose_mm=robot.get('pose_mm'),joints=robot.get('joints'),
            external_axes=robot.get('external_axes'),errors=robot.get('errors'),
            control_mode=robot.get('control_mode'),program_state=robot.get('program_state')))
    for a, b in zip(rows, rows[1:]):
        issue = None
        if not a['valid'] or not b['valid']:
            issue = 'Invalid controller telemetry'
        elif b['elapsed_s']-a['elapsed_s'] > 1:
            issue = 'Telemetry gap exceeds one second'
        else:
            # Separate kinematic errors from workspace rejections; the latter
            # can otherwise hide later joint checks. This never edits limits.
            try:
                check_path(a['robot']['pose_mm'],b['robot']['pose_mm'],a['robot']['joints'],params,None)
            except TransferError as error:
                kinematic_failures.append(dict(from_sample=a['index'],to_sample=b['index'],reason=str(error)))
            try:
                check_path(a['robot']['pose_mm'],b['robot']['pose_mm'],a['robot']['joints'],params,workspace['envelope'])
            except TransferError as error:
                issue = str(error)
        if issue:
            failures.append(dict(from_sample=a['index'],to_sample=b['index'],reason=issue))
    start, end = rows[0]['robot']['pose_mm'], rows[-1]['robot']['pose_mm']
    target = context['target_home']
    result = dict(schema='cephla.recorded-return-path.v1',created_at=datetime.now(timezone.utc).isoformat(),
        direction='Hamilton to demonstrated Home-area endpoint',
        operator_intent='Use this demonstrated path for future Hamilton-to-Home returns',
        source=dict(folder=str(folder.resolve()),sha256=hashlib.sha256(raw).hexdigest(),samples=len(rows)),
        start_pose_mm=start,demonstrated_endpoint_mm=end,saved_home=target,
        destination_decision=context.get('destination_decision','pending'),
        endpoint_instruction=context.get('endpoint_instruction',''),
        endpoint_difference=dict(position_mm=math.dist([end[k] for k in ('X','Y','Z')],[target[k] for k in ('X','Y','Z')]),
                                 yaw_degrees=wrap(end['Rz']-target['Rz'])),
        units=context['units'],trajectory=trajectory,
        validation=dict(status='blocked' if failures else 'requires_review',
            invalid_samples=sum(not s['valid'] for s in rows),
            max_gap_s=max(b['elapsed_s']-a['elapsed_s'] for a,b in zip(rows,rows[1:])),
            failure_counts=dict(Counter(f['reason'] for f in failures)),failures=failures,
            kinematic_failures=kinematic_failures,
            kinematics_passed=not kinematic_failures and all(s['valid'] for s in rows)
                and all(b['elapsed_s']-a['elapsed_s'] <= 1 for a,b in zip(rows,rows[1:])),
            params=params,workspace=workspace,
            limitations=['Sampled hand-guiding is not a collision-checked commanded trajectory.',
                         ('Saved Home remains unchanged; the demonstrated path needs a separately validated completion to Home.'
                          if context.get('destination_decision') == 'keep_saved_home' else
                          'Endpoint differs from saved Home; destination selection is pending.'),
                         'Existing automatic limits are unchanged.']),
        execution_ready=False,replay_approved=False,hardware_commands_sent=0)
    output = folder / 'return_path.json'
    output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    verified = json.loads(output.read_text())
    assert len(verified['trajectory']) == len(rows)
    assert verified['source']['sha256'] == hashlib.sha256((folder/'samples.jsonl').read_bytes()).hexdigest()
    return dict(path=str(output.resolve()),samples=len(rows),failed_segments=len(failures),
                endpoint_difference=result['endpoint_difference'],execution_ready=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    print(json.dumps(review(parser.parse_args().folder),indent=2))
