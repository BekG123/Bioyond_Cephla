"""Export stopped trial evidence; no recovery or motion commands."""
import json
import time
from proof_lift_plate import api
from hamilton_short_side_trial import FOLDER,ROOT,PLAN_SHA

path=FOLDER/'hamilton_short_side_trial01_stopped.json'
if path.exists():raise RuntimeError('Stopped receipt already saved')
s=api('state');seq=api('seq')
if not s['robot'].get('connected') and not seq['active']:
    assert api('connect',{'ip':'192.168.201.220'})['ok'];s=api('state')
assert not seq['active'] and not s['robot']['enabled'] and s['robot']['program_state']['state']=='stopped'
record=dict(at=time.time(),plan_sha256=PLAN_SHA,state=s,sequence=seq,
    status='failed_reverse_leg_controller_collision',forward_leg_started=False,
    payload='empty',physical_contact_assessment='Operator confirmed touching or caught on Hamilton; do not recover automatically.',
    recovery_attempted=False,automatic_retry=False,
    conclusion='IK validity did not establish physical or dynamic suitability. Direct speed-137 route is not accepted.')
with path.open('x') as f:json.dump(record,f,indent=2)
obs=ROOT/'reports/trajectory_smoothing/Observations.md'
with obs.open('a',encoding='utf-8') as f:
    f.write('\n\n### 2026-11-10 — Short-side Hamilton direct roundtrip, empty trial 01\n'
        '- Operator confirmed both diagonal routes and full sweep clear; removed plate before controller startup. Empty jaws; E-stop supervised.\n'
        '- New exact site-4/Home route passed IK, joint/route checks and 48 focused offline checks. One MoveL in one Lua queue per direction, speed 137; station-specific floor, global workspace unchanged.\n'
        '- Reverse leg started but controller reported axis-3/axis-4 collision faults and servo-enable faults. Program stopped, arm disabled at X338.849/Y-92.073/Z134.101/Rz-61.641. Home not reached; forward leg never started. No reset or retry.\n'
        '- Operator confirmed the arm/jaw is touching or caught on Hamilton. Failed candidate retained; not an accepted path. No automatic recovery. Records: `holder_short_side/alignment/hamilton_short_side_{empty_roundtrip01,reverse_trial01,trial01_stopped}.json`.\n')
print(json.dumps(dict(saved=str(path),status=record['status'])))
