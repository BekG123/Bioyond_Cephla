"""Supervised round trip at the operator-accepted November 1 Squid pose."""
from gripper_closure import POLICY, closure_commands
import argparse
import hashlib
import json
import time
from uuid import uuid4
from test_squid_destination_empty import api, SOURCE, SHA
from prepare_squid_destination import validate
from scope_step_trial import near

GRIP_POSITION_TOLERANCE_MM = .15


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--transit-speed', type=int, choices=(40, 137), default=40)
    parser.add_argument('--pickup-only-empty', action='store_true',
                        help='Operator confirms empty claws at Home and plate in Squid holder')
    parser.add_argument('--empty-return-only', action='store_true',
                        help='Return Home with already-open claws after confirmed release')
    args = parser.parse_args()
    if args.empty_return_only and args.pickup_only_empty:
        raise RuntimeError('Select one operation')
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA:
        raise RuntimeError('Route changed')
    candidate = json.loads(raw)
    forward = candidate['routes']['forward']
    seat = forward[-1]
    back = [seat, dict(seat, Z=seat['Z'] + 5), *reversed(forward[:-1])]
    cfg = api('robot_params')
    envelope = candidate['envelope']
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip': '192.168.201.220'})

    def ready(position, opening):
        state = api('state')
        robot = state['robot']
        if (not robot.get('connected') or robot.get('errors') or
                not robot.get('enabled') or state['sequence']['active'] or
                robot['control_mode']['mode'] != 'auto' or
                robot['program_state']['state'] != 'running'):
            raise RuntimeError('Controller not ready; no automatic recovery')
        near(robot['pose_mm'], position, .1)
        if abs(robot['external_axes']['E1'] - opening) > GRIP_POSITION_TOLERANCE_MM + 1e-9:
            raise RuntimeError('Unexpected grip position')
        actual = {k: [state['envelope'][k]['min'], state['envelope'][k]['max']]
                  for k in ('X', 'Y', 'Z')}
        if (not state['envelope']['enabled'] or actual != envelope or
                api('robot_params') != cfg or cfg != candidate['cfg'] or
                hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SHA):
            raise RuntimeError('Reviewed settings changed')
        return robot

    initial_position = forward[0] if args.pickup_only_empty else seat
    initial_opening = api('state')['robot']['external_axes']['E1'] if args.pickup_only_empty else (7 if args.empty_return_only else 3.9)
    if not 0 <= initial_opening <= 28.05:
        raise RuntimeError('Invalid initial claw feedback')
    robot = ready(initial_position, initial_opening)
    checked = dict(final_joints=robot['joints']) if args.pickup_only_empty else validate(back, robot['joints'], cfg, envelope)
    checked = validate(forward, checked['final_joints'], cfg, envelope)
    validate(back, checked['final_joints'], cfg, envelope)
    print(json.dumps({'validated': True, 'return': back, 'forward': forward}), flush=True)
    if not args.execute:
        return
    output = SOURCE.with_name(('pickup_retest_' if args.pickup_only_empty else 'roundtrip_') + uuid4().hex + '.json')
    record = dict(closure_policy=POLICY, status='validated', started_at=time.time(), source_sha256=SHA,
                  authorization='Operator confirmed destination worked perfectly and requested dropoff, empty Home, Squid pickup, loaded Home.',
                  initial_robot=robot, steps=[], transit_speed=args.transit_speed, grip_position_tolerance_mm=GRIP_POSITION_TOLERANCE_MM)
    if args.pickup_only_empty:
        record['authorization'] = 'Operator reported tilted plate, placed it in Squid holder, confirmed empty claws and requested same pickup and Home return for observation.'
    if args.empty_return_only:
        record['authorization'] = 'Operator confirmed plate stayed flat after release and claws clear; empty return Home only.'

    def save():
        output.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')

    save()  # Prove audit storage works before any physical action.
    position = initial_position
    opening = initial_opening

    def jaw(target, phase, speed=5):
        nonlocal opening
        ready(position, opening)
        step = dict(phase=phase, target_e1=target, speed=speed, status='requested')
        record['steps'].append(step)
        save()
        result = api('gripper', dict(action='move', e1=target, speed=speed))
        step['response'] = result
        save()
        if result.get('recovered'):
            raise RuntimeError('Uncertain gripper response')
        opening = target
        # Require consecutive stable feedback; never resend a jaw command.
        for _ in range(3):
            time.sleep(.25)
            ready(position, opening)
        step['after'] = api('state')['robot']
        step['status'] = 'completed'
        save()
        print(json.dumps({'phase': phase, 'e1': opening}), flush=True)

    def travel(path, phase):
        nonlocal position
        ready(position, opening)
        near(position, path[0], .1)
        validate(path, api('state')['robot']['joints'], cfg, envelope)
        for point in path[1:]:
            ready(position, opening)
            local = position['Y'] == seat['Y'] and point['Y'] == seat['Y']
            speed = 5 if local else args.transit_speed
            step = dict(phase=phase, target=point, speed=speed, status='requested')
            record['steps'].append(step)
            save()
            result = api('move', dict(x=point['X'], y=point['Y'], z=point['Z'],
                                     rz=point['Rz'], speed=speed, interpolation='linear'))
            step['response'] = result
            save()
            if result.get('recovered'):
                raise RuntimeError('Uncertain movement response')
            near(result['pose_after'], point, .1)
            position = point
            step['after'] = ready(position, opening)
            step['status'] = 'arrived'
            save()
            print(json.dumps({'phase': phase, 'pose': position}), flush=True)

    try:
        if args.empty_return_only:
            travel(back, 'empty_return_home')
            record.update(status='empty_return_home_completed', final_robot=ready(position, opening))
            return
        if args.pickup_only_empty:
            jaw(7, 'open_empty_claws_at_home')
        else:
            jaw(7, 'release_at_squid')
            travel(back, 'empty_return_home')
        travel(forward, 'return_to_squid')
        for command in closure_commands(7,3.9):
            jaw(command['target_e1_mm'], 'pickup_at_squid',command['speed'])
        travel(back, 'loaded_return_home')
        record.update(status='completed_pending_operator_inspection', final_robot=ready(position, opening))
    except Exception as error:
        record.update(status='stopped_or_failed', error=str(error))
        try:
            record['stop_response'] = api('program', {'action': 'stop'})
        except Exception as stop_error:
            record['stop_error'] = str(stop_error)
        raise
    finally:
        record['finished_at'] = time.time()
        save()
        print(json.dumps({'record': str(output), 'status': record['status']}), flush=True)


if __name__ == '__main__':
    main()
