"""Save stationary teaching and solve hover04 offline; sends no motion commands."""
import copy
import hashlib
import json
import math
import statistics
import time
from urllib.request import urlopen
from draggo import DragGoRPC
from short_side_hover_transfer import reference, PLAN as PARENT
from short_side_direct_transfer import SELECTION
from hamilton_short_side_trial import FOLDER, ROOT
from plan_short_side_hamilton import validate
from trajectory_queue import checksum

TEACHING = FOLDER/'taught_hamilton_site4_short_side_corrected04.json'
PLAN = FOLDER/'hamilton_short_side_hover04_plan.json'
KEYS = ('X','Y','Z','Rz')

def get(endpoint):
    with urlopen('http://127.0.0.1:5002/'+endpoint, timeout=5) as response:
        return json.load(response)

def save_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)

def capture():
    samples = []
    for _ in range(5):
        s = get('state'); n = DragGoRPC('192.168.201.220').info(); r = s['robot']
        assert r.get('ok') and r.get('connected') and not r.get('errors')
        assert not s['sequence']['active']
        assert not any(n[k] for k in ('moving','error','emergency','drag'))
        samples.append(dict(at=time.time(), state=s, native=n))
        time.sleep(.2)
    spread = {k:max(v['state']['robot']['pose_mm'][k] for v in samples)-min(v['state']['robot']['pose_mm'][k] for v in samples) for k in KEYS}
    assert max(spread.values()) < .02, 'Teaching position is not settled'
    target = {k:statistics.median(v['state']['robot']['pose_mm'][k] for v in samples) for k in KEYS}
    joints = {k:statistics.median(v['state']['robot']['joints'][k] for v in samples) for k in ('J1','J2','J3','J4')}
    record = dict(at=time.time(), target=target, joints=joints, samples=samples,
        config=get('robot_params'), envelope=s['envelope'], pose_spread=spread,
        external_axes=n['external_axes'],
        operator_instruction='Tiny offset at the final point; operator manually moved to ideal position and requested saving it and recalculating IK.',
        grip_setting_changed=False, motion_sent=False)
    save_new(TEACHING, record)
    return record

def build(taught):
    parent, _, _ = reference()
    assert taught['config'] == parent['config']
    for k in ('X','Y','Z'):
        assert taught['envelope'][k] == parent['global_envelope'][k]
    old = parent['routes']['forward']; target = taught['target']
    end = {k:round(target[k], 2) for k in KEYS}
    assert end['Z'] < 55 < parent['site_hover']['Z']
    turn = copy.deepcopy(parent['taught_turn'])
    ready = dict(parent['entry_ready'], Rz=end['Rz'])
    hover = dict(end, Z=parent['site_hover']['Z'])
    slow = dict(end, Z=55.0)
    forward = [turn, ready, hover, slow, end]
    reverse = list(reversed([old['start']]+forward))[1:]
    # Exact taught endpoint exception for this offline station candidate only.
    # No global travel limit or loaded runtime guard is changed.
    env = copy.deepcopy(parent['station_envelope'])
    env['Z'][0] = min(env['Z'][0], target['Z'], end['Z'])
    speeds = [137,137,137,137,5]; routes = {}
    for name, start, points, joints, expected, velocity in (
        ('forward', old['start'], forward, old['start_joints'], taught['joints'], speeds),
        ('reverse', end, reverse, taught['joints'], old['start_joints'], list(reversed(speeds)))):
        checked = validate(start, points, joints, parent['config'], env, expected)
        assert checked['workspace_valid'] and checked['ik_and_joint_limits_valid']
        routes[name] = dict(start=start, start_joints=joints, points=points, validation=checked,
            speed=137, segment_speeds=velocity, queues=1, move_l_commands=5, completion_barriers=1,
            payload=dict(header=[5,137,-1]+[start[k] for k in KEYS]+[joints[k] for k in ('J1','J2','J3','J4')],
                         points=points, segment_speeds=velocity, checksum=checksum(points,velocity)))
    record = copy.deepcopy(parent)
    record.update(revision='04', created_at=time.time(), parent_file=PARENT.name,
        parent_sha256=hashlib.sha256(PARENT.read_bytes()).hexdigest(),
        taught_endpoint_file=TEACHING.name, taught_endpoint_sha256=hashlib.sha256(TEACHING.read_bytes()).hexdigest(),
        measured_endpoint=target, commanded_endpoint=end, measured_endpoint_joints=taught['joints'],
        endpoint_delta={k:target[k]-old['points'][-1][k] for k in KEYS},
        station_envelope=env, taught_turn=turn, entry_ready=ready, site_hover=hover,
        slow_descent_start=slow, routes=routes,
        status='offline_valid_pending_supervised_trial', hardware_tested=False,
        execution_enabled=False, collision_clearance_verified=False,
        workflow=['open_at_home','accepted_approach_descent','close_to_25','lift_5_at_5','pickup_to_hamilton_via_hover04'],
        prior_trial='Revision03 retry03 reached its commanded endpoint without reported faults; operator reported a small final placement offset and retaught the endpoint.',
        reasoning='Preserve taught safe turn, hover height and speed transition at Z55. Shift the overhead and vertical approach to the corrected taught site4 XY/yaw, and seat at its taught Z.',
        limitation='Offline IK and joint checks only. Corrected route has not been run. Measured E1 is teaching telemetry, not a new grip setting.')
    save_new(PLAN, record)
    return record

def main():
    if PLAN.exists() or TEACHING.exists():
        raise RuntimeError('Preserve existing teaching/candidate; do not recapture or overwrite')
    taught = capture(); p = build(taught)
    previous = SELECTION.read_bytes()
    assert json.loads(previous)['revision'] == '03'
    with (FOLDER/'route_selection03_before_hover04.json').open('xb') as stream:
        stream.write(previous)
    selection = dict(revision='04', plan_path=str(PLAN.relative_to(ROOT.parent)),
        plan_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        status=p['status'], execution_enabled=False,
        segment_speeds=p['routes']['forward']['segment_speeds'], slow_descent_starts_at_z_mm=55,
        placement_z_mm=p['commanded_endpoint']['Z'], home_between_pickup_and_hamilton=False,
        runtime_revision_unchanged='03; explicit revision04 runtime binding required before a live trial')
    SELECTION.write_text(json.dumps(selection, indent=2), encoding='utf-8')
    note = '\n\n### 2026-11-10 - Retaught Hamilton final endpoint, revision04 offline\n'
    note += '- Retry03 motion completed without reported faults, but operator reported a small final offset; not recorded as accepted placement.\n'
    note += '- Saved stationary taught endpoint '+json.dumps(taught['target'])+'; delta from previous commanded endpoint '+json.dumps(p['endpoint_delta'])+'.\n'
    note += '- Preserve safe turn and Z137.93 overhead entry; shift overhead/vertical approach to new XY/yaw, speed137 to Z55 then speed5 to taught seating height. Pickup/grip25/slow proof lift unchanged.\n'
    note += '- Dense IK, joint winding and scoped station checks pass forward and reverse. Global workspace unchanged; only this offline candidate extends the station endpoint floor to taught Z. Selected candidate04; no motion, startup, grip command, backend reload or runtime activation. Prior trial JSON retained.\n'
    with (ROOT/'reports/trajectory_smoothing/Observations.md').open('ab') as stream:
        stream.write(note.encode('ascii'))
    print(json.dumps(dict(teaching=str(TEACHING), plan=str(PLAN), endpoint=taught['target'],
        delta=p['endpoint_delta'], command=p['commanded_endpoint'], points=p['routes']['forward']['points'],
        forward_length_mm=p['routes']['forward']['validation']['length_mm'],
        forward_joint_error=p['routes']['forward']['validation']['endpoint_joint_error'],
        reverse_joint_error=p['routes']['reverse']['validation']['endpoint_joint_error'], motion_sent=False), indent=2))

if __name__ == '__main__': main()
