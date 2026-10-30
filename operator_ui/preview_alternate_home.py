"""GET-only alternate Home preview. No robot commands or limit changes."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from autonomy import check_path, wrap
from researcher_home import queued_station_stages
from review_squid_return import get
from trajectory_queue import prepare_points

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('X', 'Y', 'Z', 'Rz')


def validate(start, joints, stages, cfg, envelope):
    current, q = dict(start), dict(joints)
    samples = [dict(pose=current, joints=q)]
    for stage in stages:
        targets = stage['points'] if stage['kind'] == 'queue' else [{**current, 'Rz':stage['rz']}]
        for target in targets:
            origin = dict(current)
            steps = max(1, math.ceil(math.dist([origin[k] for k in KEYS[:3]], [target[k] for k in KEYS[:3]])),
                        math.ceil(abs(wrap(target['Rz']-origin['Rz'])) / .5))
            for i in range(1, steps+1):
                point = {k:origin[k]+(target[k]-origin[k])*i/steps for k in KEYS[:3]}
                point['Rz'] = origin['Rz'] + wrap(target['Rz']-origin['Rz'])*i/steps
                q = check_path(current, point, q, cfg, envelope)
                q['J1'] = joints['J1'] + point['Z'] - start['Z']
                if not 0 <= q['J1'] <= 400 or abs(q['J3']) > 180:
                    raise ValueError('Joint travel exceeded')
                samples.append(dict(pose=dict(point), joints=dict(q)))
                current = point
    return samples


def main():
    state, cfg = get('state'), get('robot_params')
    r = state['robot']
    if not r.get('connected') or not r.get('ok') or r.get('errors') or state['sequence']['active']:
        raise RuntimeError('Healthy, stationary connected snapshot required.')
    start = {k:r['pose_mm'][k] for k in KEYS}
    data = json.loads((ROOT/'operator_ui/points.json').read_text(encoding='utf-8-sig'))
    point = data['points'][data['roles']['home']]
    home = dict(X=point['x'], Y=point['y'], Z=point['z_grip'], Rz=point['rz'])
    env = {k:[state['envelope'][k]['min'], state['envelope'][k]['max']] for k in KEYS[:3]}
    if not state['envelope']['enabled']:
        raise RuntimeError('Workspace must be enabled.')
    raised = {**start, 'Z':max(300., start['Z']+20., home['Z']+20.)}
    qlift = check_path(start, raised, r['joints'], cfg, env)
    sideways = {**raised, 'X': raised['X'] + 10.}
    qside = check_path(raised, sideways, qlift, cfg, env)
    candidates = []
    for x in range(230, 391, 10):
        for y in range(230, 371, 10):
            corner = {**raised, 'X':float(x), 'Y':float(y)}
            try:
                q = check_path(sideways, corner, qside, cfg, env)
                if abs(q['J2']) > 88:
                    continue
                stages = queued_station_stages(corner, home, q, cfg, env)
                previous, check = corner, q
                peak_wrist = abs(q['J4'])
                for stage in stages:
                    targets = stage['points'] if stage['kind']=='queue' else [{**previous,'Rz':stage['rz']}]
                    for target in targets:
                        check = check_path(previous, target, check, cfg, env)
                        peak_wrist = max(peak_wrist, abs(check['J4']))
                        previous = target
                if peak_wrist > 200:
                    continue
                distance = math.dist([raised[k] for k in ('X','Y')], [corner[k] for k in ('X','Y')])
                distance += math.dist([corner[k] for k in ('X','Y')], [home[k] for k in ('X','Y')])
                candidates.append((distance, corner, stages))
            except (ValueError, RuntimeError):
                continue
    if not candidates:
        raise RuntimeError('No alternate route found within the unchanged constraints.')
    for _, corner, home_stages in sorted(candidates, key=lambda item:item[0]):
        try:
            # Preserve existing bounded reviewed-step rules; no new queue exception.
            prefix, current = [], start
            for target in (raised, sideways, corner):
                steps = max(1, math.ceil(math.dist([current[k] for k in KEYS[:3]], [target[k] for k in KEYS[:3]]) / 40))
                prefix.extend({k:round(current[k]+(target[k]-current[k])*i/steps,2) for k in KEYS}
                              for i in range(1, steps+1))
                current = target
            prefix, _ = prepare_points(start, r['joints'], prefix, cfg, reviewed=True)
            # Re-plan from the quantized transmitted corner, not an idealized endpoint.
            q = r['joints']
            previous = start
            for target in prefix:
                q = check_path(previous, target, q, cfg, env)
                previous = target
            home_stages = queued_station_stages(prefix[-1], home, q, cfg, env)
            stages = [dict(kind='queue', points=prefix)] + home_stages
            samples = validate(start, r['joints'], stages, cfg, env)
            if max(abs(s['joints']['J4']) for s in samples) > 200:
                continue
            # Do not consume more of the already-small starting J2 headroom.
            if max(abs(s['joints']['J2']) for s in samples) > abs(r['joints']['J2']) + .02:
                continue
            break
        except (ValueError, RuntimeError):
            continue
    else:
        raise RuntimeError('Candidate refinement failed.')
    end = get('state')['robot']
    if any(abs(end['pose_mm'][k]-start[k]) > .05 for k in KEYS):
        raise RuntimeError('Arm moved during preview; discard.')
    plan = dict(schema='cephla.alternate-home-preview.v1', created_at=datetime.now(timezone.utc).isoformat(),
        start=start, robot=r, target=home, raised=raised, corner=prefix[-1], stages=stages,
        robot_params=cfg, envelope=env, samples=samples,
        joint_ranges={k:[min(s['joints'][k] for s in samples), max(s['joints'][k] for s in samples)] for k in ('J1','J2','J3','J4')},
        points_sha256=hashlib.sha256((ROOT/'operator_ui/points.json').read_bytes()).hexdigest(),
        payload='empty_gripper_confirmed_by_operator', translation_speed_mm_s=10, rotation_speed_deg_s=10,
        limits_changed=False, hardware_motion_sent=False, physical_clearance_verified=False,
        executable=False, candidate_count=len(candidates))
    folder = ROOT/'operator_ui/reports/alternate_home'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_preview.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, indent=2)
    print(json.dumps(dict(path=str(path), start=start, raised=raised, corner=plan['corner'], home=home,
                         stages=home_stages, joint_ranges=plan['joint_ranges'], samples=len(samples)), indent=2))


if __name__ == '__main__':
    main()
