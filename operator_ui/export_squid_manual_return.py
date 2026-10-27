"""Freeze and review the marked manual return. GET only; no motion dispatch."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

from autonomy import check_path, wrap
from researcher_home import compact_home_connection
from review_squid_return import get
from trajectory_smoothing import group_points

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'operator_ui/demonstrations/home_to_squid_attempt2_20261017_043419'
FIRST, LAST = 19700, 20451
KEYS = ('X','Y','Z','Rz')


def save(folder, name, value):
    with (folder/name).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,allow_nan=False)


if __name__ == '__main__':
    lines = []
    with (SOURCE/'samples.jsonl').open('rb') as stream:
        for line in stream:
            if not line.endswith(b'\n'):break
            row = json.loads(line)
            if FIRST <= row['index'] <= LAST:lines.append(line)
            if row['index'] >= LAST:break
    rows = [json.loads(line) for line in lines]
    if len(rows) != LAST-FIRST+1 or any(not r.get('valid') for r in rows):
        raise RuntimeError('Incomplete or invalid recording; cannot prepare replay')
    points = [dict(sample_index=r['index'],elapsed_s=r['elapsed_s'],at=r['received_at'],
        pose_mm={k:r['robot']['pose_mm'][k] for k in KEYS},joints=r['robot']['joints'],
        external_axes=r['robot'].get('external_axes'),errors=r['robot'].get('errors')) for r in rows]
    cfg, state = get('robot_params'), get('state')
    envelope = {k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in KEYS[:3]}
    points_file=ROOT/'operator_ui/points.json'
    saved=json.loads(points_file.read_text(encoding='utf-8-sig'))
    h=saved['points'][saved['roles']['home']]
    home=dict(X=h['x'],Y=h['y'],Z=h['z_grip'],Rz=h['rz'])
    reverse=list(reversed(points))
    errors=[]
    for a,b in zip(reverse,reverse[1:]):
        try:check_path(a['pose_mm'],b['pose_mm'],a['joints'],cfg,envelope)
        except Exception as error:errors.append(dict(sample=b['sample_index'],error=str(error)))
    try:
        smoothed, _, smoothing = group_points(reverse[0]['pose_mm'],reverse[0]['joints'],
                                              [r['pose_mm'] for r in reverse[1:]],cfg)
    except Exception as error:
        smoothed=[]
        smoothing=dict(passed=False,error=str(error),note='No limits changed to make smoothing pass.')
    connector={}
    for name,a,b,j in [('endpoint_to_exact_home',points[-1]['pose_mm'],home,points[-1]['joints']),
                        ('exact_home_to_endpoint',home,points[-1]['pose_mm'],h['joint_reference'])]:
        try:connector[name]=dict(passed=True,points=compact_home_connection(a,b,j,cfg,envelope))
        except Exception as error:connector[name]=dict(passed=False,error=str(error))
    start,end=points[0]['pose_mm'],points[-1]['pose_mm']
    delta={k:end[k]-home[k] for k in KEYS}
    delta['Rz']=wrap(delta['Rz'])
    summary=dict(created_at=datetime.now(timezone.utc).isoformat(),task='Manually taught Squid to approximate Home',
        source=str(SOURCE),source_first_index=FIRST,source_last_index=LAST,
        frozen_raw_sha256=hashlib.sha256(b''.join(lines)).hexdigest(),samples=len(rows),
        duration_s=rows[-1]['elapsed_s']-rows[0]['elapsed_s'],
        max_sample_gap_s=max(b['elapsed_s']-a['elapsed_s'] for a,b in zip(rows,rows[1:])),
        start=start,endpoint=end,saved_home=home,endpoint_minus_home=delta,
        endpoint_distance_from_home_mm=math.sqrt(sum(delta[k]**2 for k in KEYS[:3])),
        joint_ranges={k:[min(p['joints'][k] for p in points),max(p['joints'][k] for p in points)] for k in ('J1','J2','J3','J4')},
        controller_alert_samples=sum(bool(p['errors']) for p in points),
        box_violation_samples=sum(any(not envelope[k][0]<=p['pose_mm'][k]<=envelope[k][1] for k in KEYS[:3]) for p in points),
        max_reach_mm=max(math.hypot(p['pose_mm']['X']-cfg['base_x_mm'],p['pose_mm']['Y']-cfg['base_y_mm']) for p in points),
        reverse_runtime_failed_segments=len(errors),first_reverse_failures=errors[:5],smoothing=smoothing,
        exact_home_connections=connector,params=cfg,envelope=envelope,live_at_export=state['robot'],
        replay_approved=False,motion_commands_sent=False,
        note='Operator finished approximately Home. Raw data preserved; no saved Home change. Positive joint winding is retained. This export does not approve replay.')
    folder=ROOT/'operator_ui/demonstrations'/('squid_to_home_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:6])
    folder.mkdir()
    with (folder/'samples.jsonl').open('xb') as stream:stream.write(b''.join(lines))
    save(folder,'taught_path.json',dict(frame='robot_base_mm_degrees',points=points,replay_approved=False))
    save(folder,'reverse_candidate.json',dict(frame='robot_base_mm_degrees',points=reverse,
        smoothed_points=smoothed,replay_approved=False,runtime_failures=errors))
    save(folder,'review.json',summary)
    save(SOURCE,'return_to_home_end_20451.json',dict(end_index=LAST,marker='return_to_home_marker_20261017_054059.json',export_folder=str(folder),operator_done=True))
    print(json.dumps(dict(folder=str(folder),**{k:summary[k] for k in ('samples','duration_s','max_sample_gap_s','endpoint','endpoint_minus_home','endpoint_distance_from_home_mm','joint_ranges','box_violation_samples','max_reach_mm','controller_alert_samples','reverse_runtime_failed_segments','first_reverse_failures','smoothing','exact_home_connections')}),indent=2))
