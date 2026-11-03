"""GET-only capture and offline route validation. Never dispatches motion."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import time

from projected_pickup import ROOT, PROFILE
from prepare_squid_destination import get, validate
from scope_step_trial import near

FOLDER = ROOT/'operator_ui/reports/squid_48well_approach'
PARENT = FOLDER/'destination_calibration_y114_20261101.json'
HOME_RUN = FOLDER/'loaded_trial_f6c73cafbded4e8293324dcd72a6b4ea.json'
KEYS = ('X', 'Y', 'Z', 'Rz')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)


def main():
    first = get('state')
    time.sleep(.3)
    state = get('state')
    for sample in (first, state):
        robot = sample['robot']
        if not robot.get('connected') or not robot.get('ok') or robot.get('errors') or sample['sequence']['active']:
            raise RuntimeError('Connected, fault-free stationary capture required.')
    near(first['robot']['pose_mm'], state['robot']['pose_mm'], .05)
    robot = state['robot']
    if any(abs(first['robot']['joints'][k]-robot['joints'][k]) > .05 for k in robot['joints']):
        raise RuntimeError('Joint configuration moved during capture.')
    target = {k: robot['pose_mm'][k] for k in KEYS}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    capture_path = FOLDER/('taught_'+stamp+'.json')
    save(capture_path, dict(captured_at=datetime.now(timezone.utc).isoformat(), target=target,
        source_state=state, preceding_state=first, hardware_motion_commands_sent=False,
        payload_state='not independently verified; recorded feedback only',
        operator_intent='Save current Squid coordinate; plan from full-calibration Home and stop before descent.'))
    print(json.dumps(dict(capture=str(capture_path), target=target)), flush=True)
    if sha(PARENT) != '47a7990738aef771c09052d69a62faabf901d5b625a12ec5b17cb1f343ced6dd':
        raise RuntimeError('Parent route changed; capture retained, planning stopped.')
    parent = json.loads(PARENT.read_bytes())
    cfg = get('robot_params')
    envelope = {k: [state['envelope'][k]['min'], state['envelope'][k]['max']] for k in KEYS[:3]}
    if not state['envelope']['enabled'] or cfg != parent['cfg'] or envelope != parent['envelope']:
        raise RuntimeError('Settings changed; capture retained, no plan generated.')
    # Measured Home from the completed +Y10.4 calibration pickup/loaded return.
    evidence = json.loads(HOME_RUN.read_bytes())
    if evidence['candidate_sha256'] != sha(PARENT):
        raise RuntimeError('Home provenance belongs to another route.')
    home_robot = evidence['source_state']['robot']
    if evidence['source_state']['sequence']['state'] != 'done' or home_robot['errors']:
        raise RuntimeError('Home provenance does not show successful completion.')
    home = {k: home_robot['pose_mm'][k] for k in KEYS}
    saved_points = ROOT/'operator_ui/points.json'
    points = json.loads(saved_points.read_text(encoding='utf-8-sig'))
    saved = points['points'][points['roles']['home']]
    near(home, dict(X=saved['x'], Y=saved['y'], Z=saved['z_grip'], Rz=saved['rz']), .01)
    near(home, parent['routes']['forward'][0], .01)
    route = deepcopy(parent['routes']['forward'])
    route[0] = home
    clearance = route[-2]['Z']
    if target['Z'] + 5 > clearance:
        raise RuntimeError('Taught endpoint does not fit existing clearance; capture retained.')
    route[-2] = dict(target, Z=clearance)
    route[-1] = target  # Stored teaching only; wrapper always removes this descent.
    approach = route[:-1]
    checked = validate(approach, home_robot['joints'], cfg, envelope)
    rounded = [{k: math.floor(v*100+.5)/100 for k,v in point.items()} for point in approach]
    quantized = validate(rounded, home_robot['joints'], cfg, envelope)
    # Verify compatibility with the taught joint winding without authorizing descent.
    reference_check = validate(route, home_robot['joints'], cfg, envelope)
    delta = {k: reference_check['final_joints'][k]-robot['joints'][k] for k in robot['joints']}
    if any(abs(v) > .5 for v in delta.values()):
        raise RuntimeError('Taught joint winding mismatch; capture retained.')
    profile = json.loads(PROFILE.read_bytes())
    candidate = dict(status='offline_checked_approach_only_pending_supervised_trial',
        capture=str(capture_path), capture_sha256=sha(capture_path),
        parent=str(PARENT), parent_sha256=sha(PARENT),
        home_evidence=str(HOME_RUN), home_evidence_sha256=sha(HOME_RUN),
        saved_points_sha256=sha(saved_points), pickup_profile_sha256=sha(PROFILE),
        pickup_offset_mm=profile['pickup_correction']['distance_mm'],
        source_state=state, cfg=cfg, envelope=envelope,
        routes=dict(forward=route, approach_only=approach),
        target=target, stop_before_descent=approach[-1],
        validation=dict(approach=checked, quantized_approach=quantized,
                        taught_joint_difference=delta),
        delta_from_parent={k:target[k]-parent['routes']['forward'][-1][k] for k in KEYS},
        holder_descent_authorized=False, release_authorized=False,
        hardware_motion_commands_sent=False, collision_clearance_verified=False,
        limitations='Only approach is prepared for execution. Geometry checks do not establish physical clearance. No hardware trial performed.')
    output = FOLDER/('approach_'+stamp+'.json')
    save(output, candidate)
    print(json.dumps(dict(candidate=str(output), sha256=sha(output), approach=approach,
        capture=str(capture_path), sample_count=checked['sample_count'],
        delta=candidate['delta_from_parent'])), flush=True)


if __name__ == '__main__':
    main()
