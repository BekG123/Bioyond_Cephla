"""Extract the operator-accepted calibration sequence; no hardware access."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/1a1dbefadbc0413e8ad242d4e287fc75'
run=folder/'run.json';acceptance=folder/'operator_success.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(run)=='1cbb683aabd16d5d3004c3dd17c626afc0039c849e02061a18d2e618707e826d'
assert sha(acceptance)=='28ff70c8627ad6f067189401433f200d70232cec79ad1fad5067bac50d7230b9'
d=json.loads(run.read_bytes());a=json.loads(acceptance.read_bytes())
assert d['status']=='completed' and d['calibration_runs']==1 and a['accepted'] is True
assert a['run_sha256']==sha(run)
profile=dict(schema='cellvis24.accepted-calibration-sequence.v1',
    basis='Exact plan from the operator-accepted Cellvis full calibration, using the shared 48-well alignment and accepted Cellvis descent height.',
    source_run=dict(path=run.relative_to(ROOT).as_posix(),sha256=sha(run)),
    operator_acceptance=dict(path=acceptance.relative_to(ROOT).as_posix(),sha256=sha(acceptance),accepted=True,
                            statement=a['operator_statement']),
    camera_target_adaptation=False,grip_e1_mm=3.9,steps=d['plan']['steps'])
path=ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis24_accepted_calibration_sequence_v1.json'
with path.open('x',encoding='utf-8') as stream:json.dump(profile,stream,indent=2,allow_nan=False);stream.write('\n')
print(json.dumps(dict(path=str(path),sha256=sha(path),steps=len(profile['steps']))))
