"""Preserve operator acceptance and analyze the accepted run, without hardware."""
import hashlib,json,sys,time,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
from cellvis24_rack_route import PLAN,PLAN_SHA
folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/105936a6411a46a49fc7db88e1107cd4'
path=folder/'run.json';r=json.loads(path.read_bytes())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
accept=folder/'operator_acceptance.json'
if not accept.exists():
    with accept.open('x') as f:json.dump(dict(at=time.time(),status='operator_accepted_roundtrip',
        operator='Yes—secure throughout; flat in HOME',run_sha256=sha(path),route_sha256=PLAN_SHA,
        complete_cycles=1,plate_secure=True,home_seating_supported=True,
        limitation='Accepted held Hamilton roundtrip after supervised recovery; not an uninterrupted scanner-to-Hamilton run.'),f,indent=2)
samples=r['samples'];groups=[];group=[]
for s in samples:
    p=s['pose'];inside=all(abs(p[k]-v)<.08 for k,v in dict(X=236.19,Y=-56.22,Z=110.65).items())
    if inside:group.append(s)
    elif group:groups.append(group);group=[]
if group:groups.append(group)
turns=[]
for group in groups:
    delta=group[-1]['pose']['Rz']-group[0]['pose']['Rz'];dt=group[-1]['at']-group[0]['at']
    if abs(delta)>10 and dt>0:
        turns.append(dict(samples=len(group),duration_s=dt,yaw_start=group[0]['pose']['Rz'],yaw_end=group[-1]['pose']['Rz'],
            yaw_change_deg=delta,mean_observed_deg_s=abs(delta)/dt))
out=dict(run=str(path.relative_to(ROOT)),run_sha256=sha(path),route_sha256=sha(PLAN),
    duration_s=r['finished_at']-r['at'],turns_at_fixed_pivot=turns,
    interpretation='The seven-point MoveL queue includes two fixed-XYZ wrist turns each direction. Speed137 is a MoveL setting, not evidence of137 degrees/s.',
    limitation='Sampled host telemetry: approximate durations, not high-rate acceleration/jerk measurement.')
(folder/'rotation_analysis.json').write_text(json.dumps(out,indent=2))
print(json.dumps(out,indent=2))
