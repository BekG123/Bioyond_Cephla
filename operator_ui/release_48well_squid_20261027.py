"""One stationary release at the operator-confirmed supported Squid position."""
import json
import time
from proof_lift_plate import api, near, write, ROOT

FOLDER = ROOT / 'operator_ui/reports/projected_alignment'
OUTPUT = FOLDER / 'squid_obstruction_removed_20261027_release.json'
TARGET = dict(X=216.1, Y=374.52, Z=270.0, Rz=85.69)


def checked():
    state = api('state')
    robot = state['robot']
    if (not robot.get('connected') or not robot.get('ok') or robot.get('errors')
            or not robot.get('enabled') or state['sequence']['active']
            or robot['control_mode']['mode'] != 'auto'
            or robot['program_state']['state'] != 'running'):
        raise RuntimeError('Healthy idle running Auto required; no startup or recovery.')
    near(robot['pose_mm'], TARGET, .05)
    return state


def main():
    trial = json.loads((FOLDER / 'squid_48well_obstruction_removed_20261027_trial.json').read_bytes())
    if trial['status'] != 'motion_completed_awaiting_seating_inspection':
        raise RuntimeError('Completed approach required.')
    state = checked()
    if not 3.85 <= state['robot']['external_axes']['E1'] <= 3.95:
        raise RuntimeError('Expected unchanged 3.9 mm grip before release.')
    record = dict(at=time.time(), status='prepared', before=state,
        operator_confirmation='Flat and fully supported; preceding hands-clear and E-stop supervision retained.',
        command=dict(action='move', e1=5.0, speed=5), samples=[],
        arm_motion_commanded=False, program_restart=False, plate_after_release_verified=False)
    with OUTPUT.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2)
    try:
        record['status'] = 'release_requested'
        write(OUTPUT, record)
        response = api('gripper', record['command'])
        record['response'] = response
        if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
            raise RuntimeError('Release response uncertain; no retry.')
        deadline = time.monotonic() + 5
        stable = 0
        while stable < 3:
            state = checked()
            record['samples'].append(state)
            value = state['robot']['external_axes']['E1']
            stable = stable + 1 if abs(value - 5.0) <= .03 else 0
            if time.monotonic() > deadline:
                raise RuntimeError('Opening did not settle at 5 mm.')
            time.sleep(.15)
        record.update(status='released_at_5mm_awaiting_plate_inspection', after=state)
    except Exception as exc:
        record.update(status='stopped_or_failed', error=str(exc))
        record['stop_response'] = api('program', dict(action='stop'))
        raise
    finally:
        record['finished_at'] = time.time()
        write(OUTPUT, record)
    print(json.dumps(dict(record=str(OUTPUT), status=record['status'],
                         e1=state['robot']['external_axes']['E1'], pose=state['robot']['pose_mm'])))


if __name__ == '__main__':
    main()
