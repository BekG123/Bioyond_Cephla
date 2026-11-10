"""Record the revision03 holder-angle guard stop; read-only hardware access."""
import json
import time
from proof_lift_plate import api
from draggo import DragGoRPC
from hamilton_short_side_trial import FOLDER,ROOT

path=FOLDER/'full_sequence03_outcome.json'
if path.exists():raise RuntimeError('Outcome already saved')
run=json.loads((FOLDER/'full_sequence03_run.json').read_bytes())
assert run['status']=='failed_or_uncertain' and run['error']=='Holder changed'
reference=run['settings']['holder_e2_degrees']
trigger=[s for s in run['samples'] if abs(s['native']['external_axes']['E2']-reference)>.1]
record=dict(status='stopped_during_proof_lift',recorded_at=time.time(),
    home_completed=True,approach_completed=True,grip_target_mm=25,
    proof_lift_completed=False,hamilton_motion_started=False,
    holder_reference_degrees=reference,trigger_samples=trigger,
    operator_plate_inspection='pending',restart_sent=False,samples=[])
assert not (FOLDER/'full_sequence03_hamilton.json').exists()
s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok']
for _ in range(3):
    s=api('state');n=DragGoRPC('192.168.201.220').info()
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    assert not s['sequence']['active'] and not n['moving']
    assert s['robot']['program_state']['state']=='stopped'
    time.sleep(.2)
record['final_robot']=s['robot']
with path.open('x') as f:json.dump(record,f,indent=2)
note='''

### 2026-11-10 - Hamilton hover revision03 live trial stopped at pickup
- Operator confirmed empty jaws, plate in rotated holder, Home and new hover sweep clear, E-stop supervised. First Home preparation refused startup on stale grip25 telemetry; no travel/start command sent. Controller was subsequently observed running externally. Three unchanged-pose/near-zero-jaw samples recorded; no force-start override used. Fresh Home return completed.
- Loaded tested backend at stationary empty Home. Accepted short-side open28 approach/descent reached X306.2/Y-62.88/Z74.37/Rz87.88. Staged closing reached E1~25 mm.
- During the 5 mm proof lift at speed5, native E2 reached 91.002251 vs reference90.716612 (0.285639 degrees), exceeding the existing +/-0.1 holder monitor. Host Stop confirmed. Final Z76.730: approximately 2.36 mm lift, short of Z79.37. E1~24.999; no controller errors. Stop was followed by an interrupted move/reconnect/arrival-mismatch response; the first trigger was the holder-angle monitor.
- No Hamilton queue was uploaded or executed; new overhead path remains physically untested. Plate/contact observation pending. No release, reset, further closure or automatic retry. Original refusal, Home retry, approach, grip/lift failure, whole-run samples and stopped outcome preserved under holder_short_side/alignment/full_sequence03_*.json.
'''
with (ROOT/'reports/trajectory_smoothing/Observations.md').open('ab') as f:f.write(note.encode('ascii'))
print(json.dumps(dict(report=str(path),final_robot=record['final_robot'],holder_angle=n['external_axes']['E2'])))
