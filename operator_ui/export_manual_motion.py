"""Package an existing recording as evidence, never as an executable routine."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re


def export(folder, console_log, teaching_file):
    folder = Path(folder)
    read = lambda name: json.loads((folder/name).read_text(encoding='utf-8'))
    metadata, status = read('metadata.json'), read('status.json')
    if status['recording']:
        raise RuntimeError('Stop the recorder before exporting')
    raw = folder/'samples.jsonl'
    samples = [json.loads(line) for line in raw.read_text(encoding='utf-8').splitlines()]
    if len(samples) != status['samples']:
        raise RuntimeError('Recorder sample count does not match the file')
    if not samples or [s['index'] for s in samples] != list(range(len(samples))):
        raise RuntimeError('Missing or out-of-order samples')
    valid = sum(bool(s['valid']) for s in samples)
    gaps = [b['elapsed_s']-a['elapsed_s'] for a,b in zip(samples,samples[1:])]
    spans = []
    for sample in samples:
        if not sample['valid']:
            if spans and spans[-1]['end_index'] == sample['index']-1:
                spans[-1].update(end_index=sample['index'],end_at=sample['received_at'])
            else:
                spans.append(dict(start_index=sample['index'],end_index=sample['index'],
                    start_at=sample['requested_at'],end_at=sample['received_at'],
                    exclude_from_replay=True))
    poses = [s['robot']['pose_mm'] for s in samples if s.get('robot',{}).get('pose_mm')]
    ranges = {axis:dict(min=min(p[axis] for p in poses),max=max(p[axis] for p in poses))
              for axis in ('X','Y','Z','Rz')}
    start = datetime.fromisoformat(metadata['started_at'])
    end = datetime.fromisoformat(status['ended_at'])
    events, seen = [], set()
    # This session's console was configured to America/Los_Angeles (PDT).
    # HTTP 200 proves neither successful jaw movement nor its magnitude.
    for line in Path(console_log).read_text(encoding='utf-8',errors='replace').splitlines():
        match = re.search(r'\[([^\]]+)\] "POST /gripper HTTP/1\.1" (\d+)',line)
        if not match:
            continue
        stamp = datetime.strptime(match[1],'%d/%b/%Y %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=-7)))
        key = (stamp.isoformat(),match[2])
        if start <= stamp <= end and key not in seen:
            events.append(dict(timestamp=stamp.astimezone(timezone.utc).isoformat(),
                source='Flask HTTP access log',endpoint='/gripper',http_status=int(match[2]),
                action=None,value=None,success_verified=False,
                limitation='Request body and controller response not logged; may be move or status request.'))
            seen.add(key)
    teaching = json.loads(Path(teaching_file).read_text(encoding='utf-8'))
    draft = teaching.get('draft')
    if not draft or draft['id'] != metadata['draft_id']:
        raise RuntimeError('Teaching draft changed; review association before exporting')
    result = dict(schema='cephla.manual-motion-evidence.v1',exported_at=datetime.now(timezone.utc).isoformat(),
        title='Manual descent and grip observation',metadata=metadata,recording_status=status,
        units=dict(position='mm',orientation='degrees',joints=dict(J1='mm',J2='degrees',J3='degrees',J4='degrees')),
        source=dict(samples_file=raw.name,samples_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                    draft_id=draft['id'],draft_revision=draft['revision']),
        summary=dict(sample_count=len(samples),controller_healthy_samples=valid,
            flagged_samples=len(samples)-valid,duration_s=round((end-start).total_seconds(),3),
            average_rate_hz=round((len(samples)-1)/(samples[-1]['elapsed_s']-samples[0]['elapsed_s']),3),
            max_sample_gap_s=round(max(gaps),4),pose_ranges=ranges,final_observed_pose=poses[-1]),
        operator_annotations=[dict(action='gripper_close',reported_amount=.2,reported_as='closed gripper by 0.2',
            units='not confirmed',command_type='relative wording; actual controller command not captured',
            source='operator report',occurred_at=None,measured=False,grasp_success_verified=False),
            dict(action='stop_recording',source='operator request',
                 note='Recorder shutdown followed permission delay; recording end is later than the request. Subsequent samples are not additional teaching approval.')],
        prior_workflow_records=draft['waypoints'],gripper_http_events=events,
        excluded_fault_intervals=spans,
        training=dict(ready_for_behavior_cloning=False,use='diagnostic evidence and operator annotation only',
            gaps=['Initial descent and first collision preceded this recording.',
                  'No time-aligned gripper E1, commanded jaw targets, contact forces or verified grasp.',
                  'Controller-healthy samples do not establish collision-free or replay-safe motion.',
                  'Safe descent endpoint and reviewed action sequence have not been taught/approved.']),
        execution=dict(ready=False,replay_approved=False,motion_commands=[]),
        intended_next_session=['Repeat preparation/calibration/alignment as needed.',
            'Teach and verify a clear descent endpoint and gripper target before supervised execution.',
            'After verified grip, teach ascent, Home and Hamilton; those moves are not recorded here.'],
        samples=samples)
    path = folder/'manual_descent_grip_session.json'
    path.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    check = json.loads(path.read_text(encoding='utf-8'))
    assert len(check['samples']) == len(samples) and not check['execution']['ready']
    assert check['source']['samples_sha256'] == hashlib.sha256(raw.read_bytes()).hexdigest()
    return dict(path=str(path.resolve()),**result['summary'],gripper_requests=len(events))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    print(json.dumps(export(args.session,here/'realsense_console.stderr.log',here/'demonstrations/teaching.json'),indent=2))
