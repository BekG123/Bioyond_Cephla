"""Review a stopped descent recording; never connect to or move the robot."""
import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path


def export(folder):
    folder=Path(folder)
    status=json.loads((folder/'status.json').read_text())
    if status.get('recording'):raise ValueError('Stop the dedicated recording before export.')
    context=json.loads((folder/'teaching_context.json').read_text())
    metadata=json.loads((folder/'metadata.json').read_text())
    raw=(folder/'samples.jsonl').read_bytes()
    rows=[json.loads(line) for line in raw.splitlines()]
    backup=context['continuous_backup']
    source=(folder/backup['samples']).resolve()
    # Recover the startup interval from the pre-existing continuous recorder.
    with source.open('rb') as stream:
        size=source.stat().st_size
        offset=max(0,size-16*1024*1024)
        stream.seek(offset)
        if offset:stream.readline()
        tail=stream.read(size-stream.tell())
    prior=[]
    for line in tail.splitlines(keepends=True):
        if not line.endswith(b'\n'):continue
        row=json.loads(line)
        if row['index']>=backup['initial_observed_sample_count']-1 and row['requested_at']<metadata['started_at']:
            prior.append(row)
    (folder/'startup_backup.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in prior),encoding='utf-8')
    samples=prior+rows
    valid=[r for r in samples if r.get('valid') and r.get('robot',{}).get('pose_mm')]
    if not valid:raise ValueError('No valid pose samples.')
    final_window=rows[-10:]
    if not all(r.get('valid') and r.get('robot',{}).get('pose_mm') for r in final_window):
        raise ValueError('Final readings are invalid; do not infer an endpoint.')
    axes=('X','Y','Z','Rz')
    poses=[r['robot']['pose_mm'] for r in final_window]
    end={k:statistics.median(p[k] for p in poses) for k in axes}
    start=context['aligned_start_observation']['pose_mm']
    span={k:max(p[k] for p in poses)-min(p[k] for p in poses) for k in axes}
    xy=lambda p:math.hypot(p['X']-start['X'],p['Y']-start['Y'])
    yaw=lambda p:(p['Rz']-start['Rz']+180)%360-180
    gripper=[r['robot'].get('external_axes',{}).get('E1') for r in valid]
    gripper=[v for v in gripper if isinstance(v,(int,float))]
    blockers=[]
    if max(abs(end[k]-start[k]) for k in ('X','Y'))>.5 or abs(yaw(end))>.5:
        blockers.append('Endpoint differs in XY/yaw from aligned start; not a pure-Z replay reference.')
    if any(not r.get('valid') for r in samples):blockers.append('Recording contains invalid or fault samples; inspect before replay.')
    if any(v>.1 for v in span.values()):blockers.append('Final pose is not stationary within 0.1 mm/degree.')
    if gripper and max(gripper)-min(gripper)>.1: blockers.append('Gripper opening changed; separate opening from descent and do not interpret it as grip-force teaching.')
    result=dict(schema='cephla.descent-review.v1',replay_approved=False,
        source_sha256=hashlib.sha256(raw).hexdigest(),context=context,
        dedicated_samples=len(rows),startup_backup_samples=len(prior),
        startup_boundary_recovered=bool(prior and prior[0]['index']==backup['initial_observed_sample_count']-1),
        first_sample_at=samples[0]['requested_at'],last_sample_at=samples[-1]['received_at'],
        invalid_samples=sum(not r.get('valid') for r in samples),
        aligned_start=start,final_pose=end,z_drop_mm=start['Z']-end['Z'],
        endpoint_xy_drift_mm=xy(end),endpoint_yaw_change_deg=yaw(end),
        max_observed_xy_drift_mm=max(xy(r['robot']['pose_mm']) for r in valid),
        final_window_span=span,final_gripper_e1_mm=gripper[-1] if gripper else None,
        gripper_range_mm=[min(gripper),max(gripper)] if gripper else None,
        blockers=blockers,
        limitations=['Controller measurements, not external metrology or physical clearance verification.',
                      'No torque/force labels, preference-model training, automatic replay or reference approval.'],
        trajectory=[dict(at=r['received_at'],valid=r.get('valid'),pose_mm=r.get('robot',{}).get('pose_mm'),
                         joints=r.get('robot',{}).get('joints'),gripper=r.get('robot',{}).get('external_axes'),
                         mode=r.get('robot',{}).get('control_mode'),errors=r.get('robot',{}).get('errors')) for r in samples])
    (folder/'descent_review.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return {k:v for k,v in result.items() if k not in ('trajectory','context')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    print(json.dumps(export(parser.parse_args().folder),indent=2))
