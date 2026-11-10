"""Read-only stopped endpoint verification after jaw monitoring interrupted trial."""
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_direct_transfer import reference,FOLDER,ROOT

p,_,_=reference();path=FOLDER/'full_sequence02_outcome.json'
if path.exists():raise RuntimeError('Outcome already recorded')
seq=api('seq');s=api('state');assert not seq['active']
if not s['robot'].get('connected'):assert api('connect',{'ip':'192.168.201.220'})['ok']
samples=[];end=p['routes']['forward']['points'][-1]
for _ in range(3):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    assert r['ok'] and r['connected'] and not r['errors'] and r['program_state']['state']=='stopped'
    assert not any(n[k] for k in ('moving','error','emergency','drag'))
    near(r['pose_mm'],end,.1)
    assert abs(n['external_axes']['E1']-25)<.07
    samples.append(dict(at=time.time(),state=s,native=n));time.sleep(.2)
trial=json.loads((FOLDER/'full_sequence02_hamilton.json').read_bytes())
record=dict(at=time.time(),status='endpoint_reached_after_monitor_stop',samples=samples,sequence=seq,
    commanded_endpoint=end,hardware_queue_normal_completion_verified=False,
    operator_plate_retention_and_clearance='pending',
    reason='E1 briefly read 24.915976 mm against target 25 +/-0.07 mm near arrival; monitor stopped program. Settled E1 is about 24.997 mm.',
    controller_collision_reported=False,plate_released=False,reset_or_retry=False,
    home_between_pickup_and_hamilton=False,queue_elapsed_before_stop=trial['finished_at']-trial['started_at'])
with path.open('x') as f:json.dump(record,f,indent=2)
with (ROOT/'reports/trajectory_smoothing/Observations.md').open('a',encoding='utf-8') as f:
    f.write('\n\n### 2026-11-10 — Direct short-side pickup to Hamilton, trial 02\n'
        '- Operator cleared collision faults and confirmed empty jaws, rotated-holder plate placement and new paths clear. Empty Home return completed. Small E2 drift restored from 90.829 to 90.719 degrees at Home using the existing slow holder Lua command.\n'
        '- Accepted approach/descent, E1=25 closure and 5 mm slow lift completed. Executed direct pickup -> taught turn02 -> finish wrist turn -> Hamilton; no loaded Home detour. One three-command Lua queue at speed 137.\n'
        '- Reached X374.039/Y-184.170/Z52.030/Rz-93.560 with no controller errors. Host stopped near arrival on transient E1=24.915976, exceeding target 25 +/-0.07. Settled E1 about 24.997; three stationary endpoint readings verified. Normal queue completion remains interrupted, not retrospectively marked successful.\n'
        '- Plate retention and physical clearance await operator inspection. No release/reset/retry. Original guard-stop records retained alongside `full_sequence02_outcome.json`.\n')
print(json.dumps(dict(saved=str(path),status=record['status'],queue_elapsed=record['queue_elapsed_before_stop'])))
