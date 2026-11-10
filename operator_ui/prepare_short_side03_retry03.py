"""One authorized empty Home return; preserve earlier trial evidence."""
import hashlib
import json
import time
import argparse
from proof_lift_plate import api, near
from draggo import DragGoRPC
from short_side_full_trial import receipt, reference

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--finish-preview', action='store_true')
args = parser.parse_args()
ready_path = receipt('ready', '03', 'retry03')
path = receipt('home_resume', '03', 'retry03') if args.finish_preview else ready_path
if path.exists():
    raise RuntimeError('Preparation already attempted; inspect its evidence')
plan, parent, grip = reference('03')
expected = dict(X=297.794, Y=-5.028, Z=138.429, Rz=23.193)
record = dict(status='started', started_at=time.time(), actions=[], samples=[],
    operator_confirmed_plate_reseated_empty_jaws=True,
    authorization='Operator placed plate back in arm holder, returned empty arm near Home and requested the whole unchanged sequence. Previously confirmed route clearance and E-stop supervision remain in effect.',
    prior_result='Retry02 motion completed but operator withdrew acceptance and requested another full attempt.')

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
prior = receipt('run', '03', 'retry02')
assert json.loads(prior.read_bytes())['status'] == 'completed_awaiting_operator_inspection'
observation = receipt('operator_observation', '03', 'retry02')
if args.finish_preview:
    raw = ready_path.read_bytes(); old = json.loads(raw)
    assert old['status'] == 'failed_or_uncertain'
    assert [a['endpoint'] for a in old['actions']] == ['enable', 'program', 'researcher/api/lacry/button/move_home']
    assert all(a['response']['ok'] for a in old['actions'])
    assert s['robot']['enabled'] and s['robot']['program_state']['state'] == 'running'
    archived = receipt('pre_dispatch_refusal', '03', 'retry03')
    with archived.open('xb') as stream: stream.write(raw)
    record.update(prior_preparation_path=str(archived), prior_preparation_sha256=hashlib.sha256(raw).hexdigest(),
                  diagnosis='No Home confirmation sent: trial helper assumed 25-degree wrist increments, but existing IK Home planner proposed one checked 27.07-degree rotation.')
else:
    with observation.open('x') as stream:
        json.dump(dict(at=time.time(), source_sha256=hashlib.sha256(prior.read_bytes()).hexdigest(),
            operator_quote='Actually not yet. Retry the whole sequence. Arm back at near home, plate at arm holder',
            accepted=False, physical_outcome='not confirmed; prior telemetry retained'), stream, indent=2)
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
if args.finish_preview and record['status'] == 'completed':
    ready_path.write_text(json.dumps(record, indent=2))
print(json.dumps(dict(status=record['status'], pose=s['robot']['pose_mm'], native=n, report=str(path))))
