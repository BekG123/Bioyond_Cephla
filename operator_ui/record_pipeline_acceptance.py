"""Save operator feedback with existing telemetry; no robot command endpoints."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
def get(path):
    with urlopen('http://127.0.0.1:5002/'+path,timeout=5) as stream:
        return json.load(stream)

if __name__=='__main__':
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    audit=get('audit/status')
    folder=ROOT/'operator_ui/demonstrations'/('pipeline_feedback_'+stamp)
    folder.mkdir()
    grip=ROOT/'operator_ui/demonstrations/position_grip/be62b04354da4ac2aeac8606eed5f0f5.json'
    outcomes=[]
    audit_folder=(ROOT/'operator_ui/logs/audit'/audit['session']).resolve()
    if ROOT not in audit_folder.parents:raise ValueError('Invalid audit location')
    for path in sorted(audit_folder.glob('events_*.jsonl')):
        size=path.stat().st_size
        with path.open('rb') as stream:
            while stream.tell()<size:
                raw=stream.readline(size-stream.tell())
                if not raw.endswith(b'\n'):break
                event=json.loads(raw)
                if event.get('event')=='sequence_finished':outcomes.append(event)
    record=dict(schema='cephla.pipeline-operator-feedback.v1',recorded_at=stamp,
        operator_feedback='Looks like the full calibration pipeline worked (calibration, align, descent, grip)',
        operator_observed_pipeline_success=True,
        controller_verified_full_pipeline_success=False,
        limitation='Grip returned an error on its immediate 3.957 mm report; later native E1 feedback reached approximately 3.800 mm with no controller errors. Preserve both labels; do not relabel the original failed command or infer verified load-bearing grasp.',
        load_bearing_grasp_verified=False,replay_approved=False,
        audit_session=audit['session'],sequence_outcomes=outcomes,
        grip_source=grip.relative_to(ROOT).as_posix(),grip_source_sha256=hashlib.sha256(grip.read_bytes()).hexdigest(),
        grip_record=json.loads(grip.read_text()),live_state=get('state'),sequence_snapshot=get('seq'))
    (folder/'operator_feedback.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(file=str(folder/'operator_feedback.json'),outcomes=[dict(sequence=e.get('sequence'),state=e.get('state'),ok=(e.get('result') or {}).get('ok')) for e in outcomes])))
