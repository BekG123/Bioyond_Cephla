"""Read-only IK review from live pickup pose to saved Home; never sends POST."""
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from autonomy import check_path
from researcher_home import queued_station_stages, HOME_SPEED


def prepare():
    def get(path):
        with urlopen('http://127.0.0.1:5002'+path, timeout=5) as response:
            return json.load(response)
    state, sequence, cfg = get('/state'), get('/seq'), get('/robot_params')
    robot = state['robot']
    if sequence['active'] or not robot.get('ok') or not robot.get('connected') or robot.get('errors'):
        raise ValueError('Stationary healthy feedback required for route review.')
    if not state['envelope']['enabled']:
        raise ValueError('Enabled travel envelope required.')
    points_path = Path(__file__).with_name('points.json')
    raw = points_path.read_bytes()
    stored = json.loads(raw.decode('utf-8-sig'))
    point = stored['points'][stored['roles']['home']]
    home = dict(X=point['x'], Y=point['y'], Z=point['z_grip'], Rz=point['rz'])
    envelope = {a:(state['envelope'][a]['min'], state['envelope'][a]['max']) for a in ('X','Y','Z')}
    start = {k:robot['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    stages = queued_station_stages(start, home, robot['joints'], cfg, envelope)
    proof_lift = {**start, 'Z':start['Z']+5.0}
    check_path(start,proof_lift,robot['joints'],cfg,envelope)
    previous, joints, waypoints = start, robot['joints'], []
    length = 0.
    for stage in stages:
        legs = stage['points'] if stage['kind']=='queue' else [{**previous,'Rz':stage['rz']}]
        for end in legs:
            joints = check_path(previous, end, joints, cfg, envelope)
            length += math.dist([previous[k] for k in ('X','Y','Z')], [end[k] for k in ('X','Y','Z')])
            waypoints.append(dict(kind=stage['kind'], pose=end,
                                  expected_planar_joints={k:joints[k] for k in ('J2','J3','J4')}))
            previous = end
    result = dict(schema='cephla.pickup-home-review.v1', created_at=datetime.now(timezone.utc).isoformat(),
        live_robot=robot, start=start, home=home, source_home_sha256=hashlib.sha256(raw).hexdigest(),
        stages=stages, checked_waypoints=waypoints, translation_length_mm=length,
        config=cfg, envelope=envelope, ik_and_envelope_passed=True,
        existing_empty_home_translation_speed=HOME_SPEED, existing_wrist_speed=30,
        execution_authorized=False, physical_clearance_verified=False,
        payload='Plate, explicitly requested by operator on 2026-10-17; load-bearing grasp not yet verified.',
        proof_lift=dict(target=proof_lift,speed=5,pause_for_operator_inspection=True),
        candidate_translation_speed=10,candidate_wrist_speed=5,
        preserve_gripper=True,allow_program_restart=False,
        blockers=['Confirm clearance for a 5 mm proof lift, then inspect plate retention before the loaded return.',
                  'Existing Home action is explicitly empty-gripper; do not use its readiness flag to authorize a loaded transfer.',
                  'Review vertical departure, wrist sweep at Z300, across-to-Home and final descent clearance.'],
        limits=['IK is a sampled kinematic check, not a collision or payload-retention test.',
                'J1 is not predicted by the planar IK model; controller vertical travel is bounded by the Z envelope.',
                'Existing 137 speed has not been commissioned for this loaded departure.'])
    folder = Path(__file__).parent/'reports'/'pickup_home'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_plan.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    saved = json.loads(path.read_text())
    assert saved['checked_waypoints'][-1]['pose']==home
    assert saved['execution_authorized'] is False
    return dict(path=str(path), start=start, home=home, waypoints=len(waypoints),
                translation_length_mm=length, ik_and_envelope_passed=True,
                home_joints=waypoints[-1]['expected_planar_joints'])


if __name__ == '__main__':
    print(json.dumps(prepare(), indent=2))
