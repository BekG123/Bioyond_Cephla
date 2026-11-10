"""Record externally restored readiness after startup refusal; no motion or startup."""
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from hamilton_short_side_trial import FOLDER

path=FOLDER/'full_sequence03_empty_start.json'
if path.exists():raise RuntimeError('Startup already attempted; inspect outcome')
prior=json.loads((FOLDER/'full_sequence03_initial_home.json').read_bytes())
evidence=prior['samples'][-1]['sequence']['result']['home_startup_refusal']
assert evidence['reason']=='gripper_held_start_refused'
assert evidence['home_travel_dispatched'] is False and evidence['program_start_sent'] is False
start=prior['plan']['start']
record=dict(status='reviewed_before_start',at=time.time(),prior_refusal=evidence,samples=[],
    authorization='Operator explicitly confirmed empty jaws, plate seated in holder, startup may close jaws, all routes clear and E-stop supervised.',
    rationale='Controller changed to running externally before any startup command was sent. Verify readiness and unchanged geometry only; no override or restart.',hardware_commands=[])
for _ in range(3):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    assert r['ok'] and r['connected'] and not r['errors'] and r['enabled'] and r['program_state']['state']=='running'
    assert not s['sequence']['active'] and not any(n[k] for k in ('manual','drag','error','emergency','moving'))
    assert abs(n['external_axes']['E1'])<.1 and abs(n['external_axes']['E2']-90.71661229181757)<.1
    near(r['pose_mm'],start,.05);record['samples'].append(dict(at=time.time(),state=s,native=n));time.sleep(.2)
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    record['response']=dict(ok=True,already_running=True,program_start_sent=False)
    s=api('state');n=DragGoRPC('192.168.201.220').info();r=s['robot']
    assert r['ok'] and not r['errors'] and r['enabled'] and r['program_state']['state']=='running'
    assert not any(n[k] for k in ('manual','drag','error','emergency','moving')) and abs(n['external_axes']['E1'])<.1
    near(r['pose_mm'],start,.05)
    record.update(status='completed',final_state=s,final_native=n)
except Exception as error:
    record.update(status='failed_or_uncertain',error=str(error));raise
finally:
    record['finished_at']=time.time();path.write_text(json.dumps(record,indent=2))
print(json.dumps(dict(status=record['status'],response=record['response'],pose=r['pose_mm'])))
