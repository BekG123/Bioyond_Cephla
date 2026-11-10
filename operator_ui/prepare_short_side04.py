"""One authorized empty Home return; preserve earlier trial evidence."""
import hashlib
import json
import time
from proof_lift_plate import api, near
from draggo import DragGoRPC
from short_side_full_trial import receipt, reference

path = receipt('ready', '04')
if path.exists(): raise RuntimeError('Preparation already attempted; inspect evidence')
plan, parent, grip = reference('04')
expected = dict(X=269.654, Y=2.618, Z=164.203, Rz=6.902)
record = dict(status='started', started_at=time.time(), actions=[], samples=[],
    operator_confirmed_plate_reseated_empty_jaws=True,
    authorization='Operator placed plate back in arm holder, returned empty arm near Home and requested the whole unchanged sequence. Previously confirmed route clearance and E-stop supervision remain in effect.',
    prior_result='Retry03 reached its commanded endpoint; operator retaught a small final offset. Run revision04.')

def save():
    path.write_text(json.dumps(record, indent=2))

def read(stationary=False):
    s = api('state'); n = DragGoRPC('192.168.201.220').info(); r = s['robot']
    record['samples'].append(dict(at=time.time(), state=s, native=n))
    assert r.get('ok') and r.get('connected') and not r.get('errors')
    assert not any(n[k] for k in ('manual', 'drag', 'emergency', 'error'))
    assert abs(n['external_axes']['E1']) < .15
    if stationary: assert not n['moving']
    return s, n

def call(endpoint, body):
    action = dict(at=time.time(), endpoint=endpoint, body=body)
    record['actions'].append(action); save()
    result = api(endpoint, body); action['response'] = result; save()
    assert result.get('ok'), result
    return result

s = api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:
    assert api('connect', {'ip':'192.168.201.220'})['ok']
for _ in range(3):
    s, n = read(True); near(s['robot']['pose_mm'], expected, .1)
    assert not s['sequence']['active']
    time.sleep(.2)
assert api('researcher/api/status')['hand_guiding']['state'] == 'off'
assert not api('researcher/api/lacry/state')['running']['active']
with path.open('x') as stream: json.dump(record, stream, indent=2)
try:
    if not s['robot']['enabled']: call('enable', {'confirm':True})
    if s['robot']['program_state']['state'] != 'running':
        # Plate is back in holder and native E1 is near zero: the cached loaded
        # reading is stale. Existing safe_start stops paused code before start.
        call('program', {'action':'start', 'force':True})
    s, n = read(True); near(s['robot']['pose_mm'], expected, .1)
    assert s['robot']['enabled'] and s['robot']['program_state']['state'] == 'running'
    record['jaw_position_preserved_mm'] = n['external_axes']['E1']
    home = call('researcher/api/lacry/button/move_home', {})['plan']
    assert home['dispatch'] == 'ik_home_return'
    near(home['start'], s['robot']['pose_mm'], .05)
    near(home['home'], parent['home'], .01)
    stages = home['stages']; assert 3 <= len(stages) <= 6
    assert stages[0]['kind'] == 'queue' and len(stages[0]['points']) == 1
    near(stages[0]['points'][0], dict(home['start'], Z=300), .01)
    last = home['start']['Rz']
    for stage in stages[1:-1]:
        assert stage['kind'] == 'rotate'
        assert parent['home']['Rz']-.01 <= stage['rz'] < last and last-stage['rz'] <= 30.01
        last = stage['rz']
    assert abs(last-parent['home']['Rz']) < .01
    assert stages[-1]['kind'] == 'queue' and len(stages[-1]['points']) == 2
    near(stages[-1]['points'][0], dict(parent['home'], Z=300), .01)
    near(stages[-1]['points'][1], parent['home'], .01)
    record['home_plan'] = home; save()
    call('researcher/api/lacry/confirm', {'ready':True, 'plan_id':home['id']})
    deadline = time.monotonic()+120
    while time.monotonic() < deadline:
        s, n = read(); seq = api('seq'); save()
        if not seq['active']:
            assert seq['state'] == 'done' and seq['result'].get('ok'), seq
            s, n = read(True); near(s['robot']['pose_mm'], parent['home'], .1)
            record.update(status='completed', final_state=s, final_sequence=seq,
                          jaw_position_preserved_mm=n['external_axes']['E1'])
            break
        time.sleep(.2)
    else: raise RuntimeError('Home timed out')
except Exception as error:
    record.update(status='failed_or_uncertain', error=str(error))
    if api('seq')['active']: record['stop_response'] = api('researcher/api/lacry/stop', {})
    raise
finally:
    record['finished_at'] = time.time(); save()
print(json.dumps(dict(status=record['status'], pose=s['robot']['pose_mm'], native=n, report=str(path))))
