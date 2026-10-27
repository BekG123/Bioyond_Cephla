"""Read-only Home/current IK review. HTTP GET only; never dispatches motion."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

from autonomy import check_path, wrap
from review_squid_return import get, geometric_ik

ROOT = Path(__file__).resolve().parents[1]


def review(start, target, joints, cfg, envelope, via=None):
    height = max(300., start['Z'] + 20, target['Z'] + 20)
    path = [dict(start), {**start, 'Z':height}, {**target, 'Z':height}, dict(target)]
    if via:
        planar = [(start['X'],start['Y']), *via, (target['X'],target['Y'])]
        lengths = [math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(planar,planar[1:])]
        distance = 0.
        path = [dict(start), {**start,'Z':height}]
        for xy, length in zip(planar[1:],lengths):
            distance += length
            path.append(dict(X=xy[0],Y=xy[1],Z=height,
                             Rz=start['Rz']+wrap(target['Rz']-start['Rz'])*distance/sum(lengths)))
        path.append(dict(target))
    current_joints = dict(joints)
    samples, legs = [], []
    for index, (left, right) in enumerate(zip(path, path[1:]), 1):
        origin = dict(current_joints)
        try:
            check_path(left, right, origin, cfg, envelope)
            validation = dict(passed=True)
        except Exception as error:
            validation = dict(passed=False, error=str(error))
        n = max(1, math.ceil(max(abs(right[k]-left[k]) for k in ('X','Y','Z'))),
                math.ceil(abs(wrap(right['Rz']-left['Rz']))))
        for i in range(n+1):
            f = i/n
            pose = {k:left[k]+(right[k]-left[k])*f for k in ('X','Y','Z')}
            pose['Rz'] = left['Rz']+wrap(right['Rz']-left['Rz'])*f
            a, b = geometric_ik(pose['X'], pose['Y'],
                                (current_joints['J2'],current_joints['J3']), cfg)
            c = origin['J4']+f*wrap(right['Rz']-left['Rz'])-(a+b-origin['J2']-origin['J3'])
            current_joints.update(J2=a,J3=b,J4=c)
            reach = math.hypot(pose['X']-cfg['base_x_mm'],pose['Y']-cfg['base_y_mm'])
            samples.append(dict(leg=index,pose=pose,J2=a,J3=b,J4=c,reach_mm=reach))
        legs.append(dict(leg=index,target=right,diagnostic_joints={k:current_joints[k] for k in ('J2','J3','J4')},runtime_check=validation))
    j2_limit = abs(cfg['j2_min_deg'])-cfg['j2_margin_deg']
    j4_limit = min(cfg['j4_pref_abs_deg'],cfg['j4_hard_abs_deg']-5)
    violations = dict(J2=[s for s in samples if abs(s['J2'])>j2_limit],
                      J4=[s for s in samples if abs(s['J4'])>j4_limit])
    return dict(waypoints=path,legs=legs,samples=samples,
        ranges={k:[min(s[k] for s in samples),max(s[k] for s in samples)] for k in ('J2','J3','J4','reach_mm')},
        first_joint_violations={k:v[0] if v else None for k,v in violations.items()},
        runtime_passed=all(leg['runtime_check']['passed'] for leg in legs),
        physical_clearance_verified=False,speed_137_validated=False,executable=False)


if __name__ == '__main__':
    state, cfg = get('state'), get('robot_params')
    robot = state['robot']
    if not robot.get('connected') or not robot.get('ok') or robot.get('errors'):
        raise RuntimeError('Healthy live robot snapshot required; no commands sent')
    current = {k:robot['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    points_file = ROOT/'operator_ui/points.json'
    points = json.loads(points_file.read_text(encoding='utf-8-sig'))
    p = points['points'][points['roles']['home']]
    home = dict(X=p['x'],Y=p['y'],Z=p['z_grip'],Rz=p['rz'])
    envelope = {k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
    result = dict(created_at=datetime.now(timezone.utc).isoformat(),live_robot=robot,
        params=cfg,envelope=envelope,home_source_sha256=hashlib.sha256(points_file.read_bytes()).hexdigest(),
        home_joint_reference=p['joint_reference'],motion_commands_sent=False,
        current_to_home=review(current,home,robot['joints'],cfg,envelope),
        home_to_current=review(home,current,p['joint_reference'],cfg,envelope),
        staged_current_to_home=review(current,home,robot['joints'],cfg,envelope,[(313.939,325.519),(350.,200.)]),
        staged_home_to_current=review(home,current,p['joint_reference'],cfg,envelope,[(350.,200.),(313.939,325.519)]),
        notes=['Raw planar IK diagnostic continues past runtime rejection to show joint ranges; it is not execution approval.',
               'Each direction preserves its own measured/taught starting joint winding; equivalent TCP yaw does not imply the same physical winding.',
               'Z300 is a proposed travel height, not verified fixture clearance. J1 travel, collisions and speed dynamics require separate validation.'])
    folder = ROOT/'operator_ui/reports/squid'
    folder.mkdir(parents=True,exist_ok=True)
    target = folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_home_current_ik_'+uuid4().hex[:6]+'.json')
    with target.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(file=str(target),current=current,home=home,
        reviews={name:{k:result[name][k] for k in ('waypoints','ranges','runtime_passed')} for name in ('current_to_home','home_to_current','staged_current_to_home','staged_home_to_current')}),indent=2))
