"""Preserve partial success and stopped Hamilton failure; no motion/reset."""
import json
import time
from proof_lift_plate import api
from short_side_full_trial import FOLDER,ROOT

path=FOLDER/'full_sequence01_outcome.json'
if path.exists():raise RuntimeError('Outcome already recorded')
s=api('state');seq=api('seq')
if not s['robot'].get('connected') and not seq['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok'];s=api('state')
assert not seq['active'] and not s['robot']['enabled'] and s['robot']['program_state']['state']=='stopped'
trial=json.loads((FOLDER/'full_sequence01_hamilton.json').read_bytes());goal=trial['plan']['points'][0]
samples=[x for x in trial['samples'] if x.get('robot',{}).get('pose_mm')]
closest=min(samples,key=lambda x:sum((x['robot']['pose_mm'][k]-goal[k])**2 for k in ('X','Y','Z')))
record=dict(at=time.time(),status='pickup_and_home_completed_hamilton_failed',
    state=s,sequence=seq,closest_turning_waypoint_sample=closest,
    completed_phases=['empty Home','accepted open-jaw approach/descent','E1 25 mm closure','5 mm lift at speed 5','loaded Home'],
    physical_plate_retention='pending operator inspection; telemetry alone does not verify',
    fault='Axis 4 collision reported after taught waypoint, on final site-4 approach',
    route_accepted=False,gripper_released=False,reset_attempted=False,retry_attempted=False)
with path.open('x') as f:json.dump(record,f,indent=2)
with (ROOT/'reports/trajectory_smoothing/Observations.md').open('a',encoding='utf-8') as f:
    f.write('\n\n### 2026-11-10 — Short-side full sequence trial 01\n'
        '- Operator cleared faults and repositioned; confirmed empty jaws, plate in rotated holder and all revised routes clear. Existing Lacry IK returned empty arm to true Home.\n'
        '- Accepted corrected02 approach and 30 mm descent at 137, staged closure to E1=25 at speed 5, 5 mm lift at speed 5, and loaded Lacry Home return completed without reported faults. Retention still requires physical observation.\n'
        '- Revised two-command Hamilton Lua queue at 137 reached taught turning point X332.670/Y-70.401/Z134.093/Rz-55.610 accurately. Axis-4 collision fault followed on the final approach. Stopped/disabled at X336.342/Y-82.327/Z117.934/Rz-58.618; E1 about 25.432 after fault. No release, reset or retry.\n'
        '- The taught waypoint was executed; it did not establish clearance for the following simultaneous wrist turn/descent. Revised path remains unaccepted. All phase logs and final controller state saved under `holder_short_side/alignment/full_sequence01_*.json`.\n')
print(json.dumps(dict(saved=str(path),status=record['status'])))
