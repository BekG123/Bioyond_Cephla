"""Capture a new taught endpoint; validate a candidate without moving hardware."""
import hashlib
import json
import math
import time
from copy import deepcopy
from datetime import datetime, timezone
from test_squid_destination_empty import api, SOURCE, SHA
from prepare_squid_destination import validate
from scope_step_trial import near


def main():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA:
        raise RuntimeError('Parent route changed')
    parent = json.loads(raw)
    first = api('state')
    time.sleep(.3)
    state = api('state')
    robot = state['robot']
    if not robot.get('connected') or not robot.get('ok') or robot.get('errors') or state['sequence']['active']:
        raise RuntimeError('Connected, stationary, fault-free arm required')
    near(first['robot']['pose_mm'], robot['pose_mm'], .05)
    target = {k: robot['pose_mm'][k] for k in ('X', 'Y', 'Z', 'Rz')}
    cfg = api('robot_params')
    env = {k: [state['envelope'][k]['min'], state['envelope'][k]['max']] for k in ('X','Y','Z')}
    if cfg != parent['cfg'] or env != parent['envelope'] or not state['envelope']['enabled']:
        raise RuntimeError('Parent settings changed')
    forward = deepcopy(parent['routes']['forward'])
    if target['Z'] + 5 > forward[-2]['Z']:
        raise RuntimeError('Endpoint does not fit retained clearance height')
    forward[-2] = dict(target, Z=forward[-2]['Z'])
    forward[-1] = target
    reverse = [target, dict(target, Z=target['Z']+5), *reversed(forward[:-1])]
    back = validate(reverse, robot['joints'], cfg, env)
    outward = validate(forward, back['final_joints'], cfg, env)
    if any(abs(outward['final_joints'][k]-robot['joints'][k]) > .5 for k in robot['joints']):
        raise RuntimeError('Arrival joint winding does not match teaching')
    baseline = validate(parent['routes']['forward'], back['final_joints'], cfg, env)
    expected = parent['validation']['forward']['final_joints']
    if any(abs(baseline['final_joints'][k]-expected[k]) > .5 for k in expected):
        raise RuntimeError('Home winding differs from parent')
    checks = dict(forward=outward, reverse=back)
    for name, path, initial in [('forward', forward, back['final_joints']), ('reverse', reverse, robot['joints'])]:
        rounded = [{k: math.floor(v*100+.5)/100 for k,v in p.items()} for p in path]
        checks[name]['quantized_final_joints'] = validate(rounded, initial, cfg, env)['final_joints']
    record = dict(status='offline_checked_pending_supervised_trial', captured_at=datetime.now(timezone.utc).isoformat(),
                  parent=str(SOURCE), parent_sha256=SHA, source_state=state, cfg=cfg, envelope=env,
                  routes=dict(forward=forward, reverse=reverse), validation=checks,
                  change='Microscope legs leveled and microscope repositioned. Operator designated current pose as new Squid dropoff. Preserve Home/transit; replace overhead XY/yaw and seated endpoint.',
                  delta_from_parent={k:target[k]-parent['routes']['forward'][-1][k] for k in target},
                  handling=dict(release_mm=7, grip_mm=3.9, grip_speed=5, lift_mm=5, local_speed=5, transit_speed=40),
                  hardware_motion_commands_sent=False, deployed=False, collision_clearance_verified=False,
                  limitations='IK and workspace checks do not establish physical clearance around the relocated microscope. Candidate has not been executed.')
    output = SOURCE.with_name('destination_leveled_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(candidate=str(output), sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                         forward=forward, delta=record['delta_from_parent'],
                         validation={k: {a:b for a,b in v.items() if a!='samples'} for k,v in checks.items()})))


if __name__ == '__main__':
    main()
