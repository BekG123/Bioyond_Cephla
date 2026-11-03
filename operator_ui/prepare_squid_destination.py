"""Capture the current taught Squid destination and calculate routes. No motion APIs."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
import urllib.request

from autonomy import check_path, wrap, TransferError
from projected_pickup import ROOT, load, accepted_grip
from scope_compact137 import accepted
from scope_step_trial import near
from squid_48well_higher_route import reference, SOURCE
from squid_48well_handling import settings

KEYS = ('X', 'Y', 'Z', 'Rz')


def get(path):
    with urllib.request.urlopen('http://127.0.0.1:5002/'+path, timeout=5) as response:
        return json.load(response)


def validate(path, initial, cfg, envelope):
    """Check dense linear/yaw samples, retaining the initial joint winding."""
    q = deepcopy(initial)
    offset = q['J1']-path[0]['Z']
    samples = []
    for a, b in zip(path, path[1:]):
        delta = wrap(b['Rz']-a['Rz'])
        count = max(1, math.ceil(math.dist([a[k] for k in KEYS[:3]],
                                         [b[k] for k in KEYS[:3]])/.5),
                    math.ceil(abs(delta)/.25))
        previous = a
        for i in range(1, count+1):
            point = {k:a[k]+(b[k]-a[k])*i/count for k in KEYS[:3]}
            point['Rz'] = a['Rz']+delta*i/count
            q = check_path(previous, point, q, cfg, envelope)
            q['J1'] = point['Z']+offset
            if not 0 <= q['J1'] <= 400 or abs(q['J3']) > 180:
                raise TransferError('Candidate exceeds J1/J3 limits.')
            samples.append(dict(pose=point, joints=deepcopy(q)))
            previous = point
    return dict(sample_count=len(samples), final_joints=q,
                joint_ranges={k:[min(s['joints'][k] for s in samples),
                                 max(s['joints'][k] for s in samples)] for k in q},
                samples=samples)


def build(state, cfg):
    robot = state['robot']
    if not robot.get('connected') or not robot.get('ok') or robot.get('errors') or state['sequence']['active']:
        raise TransferError('Connected, fault-free and stationary arm required for capture.')
    parent, old = reference()
    envelope = {k:[state['envelope'][k]['min'], state['envelope'][k]['max']] for k in KEYS[:3]}
    if not state['envelope']['enabled'] or envelope != parent['envelope'] or cfg != parent['cfg']:
        raise TransferError('Workspace or joint settings differ from the parent route.')
    target = {k:robot['pose_mm'][k] for k in KEYS}
    if not all(math.isfinite(v) for v in target.values()) or target['Z']+5 > old[-2]['Z']:
        raise TransferError('Taught endpoint does not fit the existing clearance height and 5 mm lift.')
    route = deepcopy(old)
    route[-2] = dict(target, Z=old[-2]['Z'])
    route[-1] = target
    points = json.loads((ROOT/'operator_ui/points.json').read_bytes())
    home = points['points'][points['roles']['home']]
    near(route[0],dict(X=home['x'],Y=home['y'],Z=home['z_grip'],Rz=home['rz']),.001)
    _, _, hashes, trials = accepted()
    home_q = trials['reverse']['final_robot']['joints']
    forward = validate(route, home_q, cfg, envelope)
    delta = {k:forward['final_joints'][k]-robot['joints'][k] for k in home_q}
    if any(abs(v) > .5 for v in delta.values()):
        raise TransferError('Predicted arrival does not match the taught joint winding.')
    reverse = [target, dict(target, Z=target['Z']+5), *reversed(route[:-1])]
    backward = validate(reverse, robot['joints'], cfg, envelope)
    if any(abs(backward['final_joints'][k]-home_q[k]) > .5 for k in home_q):
        raise TransferError('Return route does not match the accepted Home joint winding.')
    profile, profile_hash = load()
    if not accepted_grip(profile):
        raise TransferError('Accepted 48-well grip evidence required.')
    return dict(status='offline_checked_pending_supervised_trial', captured_at=datetime.now(timezone.utc).isoformat(),
        source_state=state, parent=str(SOURCE.relative_to(ROOT)),
        parent_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(), accepted_parent_hashes=hashes,
        saved_points_sha256=hashlib.sha256((ROOT/'operator_ui/points.json').read_bytes()).hexdigest(),
        pickup_profile_sha256=profile_hash, cfg=cfg, envelope=envelope,
        routes=dict(forward=route, reverse=reverse),
        validation=dict(forward=forward, reverse=backward, taught_joint_difference=delta),
        handling=settings(), lift_mm=5, lift_speed=5, descent_speed=5, parent_transit_speed=137,
        change='Preserve Home lift and X354/Y270 transit. Replace only overhead approach XY/yaw and final seated pose with current teaching.',
        controller_quantization=dict(resolution_mm_deg=.01, endpoint={k:math.floor(v*100+.5)/100 for k,v in target.items()}),
        hardware_motion_commands_sent=False, deployed=False, collision_clearance_verified=False,
        limitations='IK/workspace checks do not model microscope, holder, gripper or plate collision volumes. New approach needs supervised physical validation. Existing executor still uses its original pinned route.')


def main():
    state = get('state')
    time.sleep(.2)
    fresh = get('state')
    if not state['robot'].get('connected') or not fresh['robot'].get('connected'):
        raise TransferError('Connect through the Flask console before capturing.')
    near(state['robot']['pose_mm'], fresh['robot']['pose_mm'], .05)
    candidate = build(fresh, get('robot_params'))
    # Also check the controller's rounded waypoint geometry in both directions.
    for direction, path in candidate['routes'].items():
        rounded = [{k:math.floor(p[k]*100+.5)/100 for k in KEYS} for p in path]
        initial = (accepted()[3]['reverse']['final_robot']['joints'] if direction=='forward'
                   else fresh['robot']['joints'])
        checked = validate(rounded, initial, candidate['cfg'], candidate['envelope'])
        candidate['validation'][direction]['quantized_route_checked'] = True
        candidate['validation'][direction]['quantized_final_joints'] = checked['final_joints']
    output = ROOT/'operator_ui/reports/squid_48well_approach'/('destination_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(candidate, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(candidate=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                         route=candidate['routes']['forward'],validation={k:{a:b for a,b in v.items() if a!='samples'}
                         for k,v in candidate['validation'].items() if k in ('forward','reverse')})))


if __name__ == '__main__':
    main()
