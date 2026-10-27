"""Offline export of the original Home-to-Squid demonstration; no motion."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from autonomy import check_path, wrap
from sequences import get_robot_params

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'operator_ui/demonstrations/home_to_squid_20261017_042235'
KEYS=('X','Y','Z','Rz')
def save(name,value):
    with (FOLDER/name).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,allow_nan=False)

if __name__=='__main__':
    status=json.loads((FOLDER/'status.json').read_text())
    if status.get('recording'):raise RuntimeError('Stop dedicated recording before export.')
    source=FOLDER/'samples.jsonl';raw=source.read_bytes()
    samples=[json.loads(line) for line in raw.splitlines() if line.strip()]
    valid=[s for s in samples if s.get('valid') and all(k in s['robot'].get('pose_mm',{}) for k in KEYS)]
    if not valid:raise RuntimeError('No valid robot poses.')
    points=[dict(sample_index=s['index'],at=s['received_at'],elapsed_s=s['elapsed_s'],
                 pose_mm={k:s['robot']['pose_mm'][k] for k in KEYS},joints=s['robot']['joints'],
                 e1_mm=s['robot'].get('external_axes',{}).get('E1'),
                 mode=s['robot'].get('control_mode',{}).get('mode')) for s in valid]
    start,end=points[0]['pose_mm'],points[-1]['pose_mm']
    path_length=sum(math.dist([a['pose_mm'][k] for k in KEYS[:3]],[b['pose_mm'][k] for k in KEYS[:3]]) for a,b in zip(points,points[1:]))
    moved=[p for p in points if math.dist([p['pose_mm'][k] for k in KEYS[:3]],[start[k] for k in KEYS[:3]])>.5 or abs(wrap(p['pose_mm']['Rz']-start['Rz']))>.5]
    context=json.loads((FOLDER/'teaching_context.json').read_text(encoding='utf-8-sig'))
    box=context['initial_state']['envelope']
    envelope={k:(box[k]['min'],box[k]['max']) for k in KEYS[:3]}
    cfg=get_robot_params();failures=[]
    for a,b in zip(points,points[1:]):
        try:check_path(a['pose_mm'],b['pose_mm'],a['joints'],cfg,envelope)
        except Exception as error:failures.append(dict(sample_index=b['sample_index'],reason=str(error)))
    alerts=[dict(at=s['received_at'],errors=s.get('robot',{}).get('errors')) for s in samples if s.get('robot',{}).get('errors')]
    end_violations={k:dict(measured=end[k],allowed=list(envelope[k])) for k in KEYS[:3] if not envelope[k][0]<=end[k]<=envelope[k][1]}
    e1=[p['e1_mm'] for p in points if type(p['e1_mm']) in (int,float)]
    tail=points[-10:]
    summary=dict(schema='cephla.manual-route-review.v1',task='Home to Squid',exported_at=datetime.now(timezone.utc).isoformat(),
        source_sha256=hashlib.sha256(raw).hexdigest(),source='samples.jsonl',
        samples=len(samples),valid_samples=len(valid),read_failures=status['failures'],
        duration_s=round(samples[-1]['elapsed_s']-samples[0]['elapsed_s'],3),
        first_motion_at=moved[0]['at'] if moved else None,start=start,endpoint=end,
        final_joints=points[-1]['joints'],e1_range_mm=[min(e1),max(e1)],final_e1_mm=points[-1]['e1_mm'],
        sampled_translation_length_mm=round(path_length,3),
        max_sample_gap_s=round(max(b['elapsed_s']-a['elapsed_s'] for a,b in zip(samples,samples[1:])),3),
        final_ten_pose_spread={k:round(max(p['pose_mm'][k] for p in tail)-min(p['pose_mm'][k] for p in tail),4) for k in KEYS},
        controller_alert_samples=alerts,offline_replay_check=dict(passed=not failures,failed_segments=len(failures),
            endpoint_workspace_violations=end_violations,first_failures=failures[:10],
            explanation='Manual reachability does not establish automatic path feasibility. No limits changed.'),
        replay_approved=False,reverse_route_approved=False,
        note='Original hand-guided path retained. Jaw position is observed, not a taught grip-force command. No automated smoothing or replay applied.')
    save('teaching_summary.json',summary)
    save('taught_path.json',dict(schema='cephla.manual-route.v1',task='Home to Squid',frame='robot_base_mm_degrees',
        source_sha256=summary['source_sha256'],replay_approved=False,points=points))
    print(json.dumps(summary,indent=2))
