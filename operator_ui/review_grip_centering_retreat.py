"""One authorized open-jaw, vertical retreat; preserve an audit before commands."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from autonomy import check_path


def api(path, body=None):
    request = Request('http://127.0.0.1:5002' + path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=120) as response:
        return json.load(response)


def main():
    if sys.argv[1:] != ['--operator-confirmed']:
        raise RuntimeError('Explicit opening and vertical retreat confirmation required.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = Path(__file__).parent / 'reports/grip_centering' / stamp
    folder.mkdir(parents=True, exist_ok=False)
    log = dict(authorization='Operator confirmed opening to 28 mm and straight retreat to Z300 clear; plate supported, hands clear, E-stop supervised.',
               started_at=time.time(), events=[], status='preflight')
    output = folder / 'retreat.json'

    def save():
        output.write_text(json.dumps(log, indent=2, allow_nan=False), encoding='utf-8')

    def healthy():
        state = api('/state')
        robot = state['robot']
        if (state['sequence']['active'] or not robot.get('ok') or not robot.get('connected')
                or robot.get('errors') or not robot.get('enabled')
                or robot['control_mode']['mode'] != 'auto'
                or robot['program_state']['state'] != 'running'):
            raise RuntimeError('Require idle, healthy, already-running Auto. No reset or enable.')
        return state

    def command(path, body):
        event = dict(at=time.time(), path=path, request=body)
        log['events'].append(event)
        save()
        result = api(path, body)
        event['response'] = result
        save()
        if result.get('ok') is not True or result.get('recovered') or result.get('warnings'):
            raise RuntimeError(str(result))
        return result

    try:
        state = healthy()
        log['before'] = state
        pose = state['robot']['pose_mm']
        expected = dict(X=309.508, Y=-66.073, Z=70.461, Rz=89.174)
        if any(abs(pose[k] - v) > .05 for k, v in expected.items()):
            raise RuntimeError('Arm changed from the reviewed pickup pose.')
        if abs(state['robot']['external_axes']['E1'] - 6.3) > .05:
            raise RuntimeError('Jaw opening changed from 6.3 mm.')
        envelope = {a: [state['envelope'][a]['min'], state['envelope'][a]['max']]
                    for a in ('X', 'Y', 'Z')}
        if not state['envelope']['enabled']:
            raise RuntimeError('Workspace must remain enabled.')
        goal = {**expected, 'Z': 300.0}
        log['checked_joints'] = check_path(pose, goal, state['robot']['joints'],
                                         api('/robot_params'), envelope)
        save()
        command('/gripper', dict(action='move', e1=28, speed=5))
        opened = healthy()
        log['after_open'] = opened
        save()
        if abs(opened['robot']['external_axes']['E1'] - 28) > .05:
            raise RuntimeError('Open jaws were not confirmed.')
        if any(abs(opened['robot']['pose_mm'][k] - v) > .05 for k, v in expected.items()):
            raise RuntimeError('Arm moved during opening.')
        print('Jaws confirmed open at 28 mm. Beginning authorized vertical retreat.', flush=True)
        command('/move', dict(x=goal['X'], y=goal['Y'], z=goal['Z'], rz=goal['Rz'],
                             speed=10, interpolation='linear'))
        final = healthy()
        log['after'] = final
        if any(abs(final['robot']['pose_mm'][k] - v) > .1 for k, v in goal.items()):
            raise RuntimeError('Retreat endpoint not confirmed.')
        if abs(final['robot']['external_axes']['E1'] - 28) > .05:
            raise RuntimeError('Jaw opening changed during retreat.')
        log.update(status='completed', finished_at=time.time())
        save()
        print(json.dumps(dict(record=str(output), pose=final['robot']['pose_mm'],
                              e1=final['robot']['external_axes']['E1']), indent=2))
    except Exception as error:
        log.update(status='failed_or_uncertain', error=str(error), finished_at=time.time())
        save()
        print('Stopped; no automatic retry. Audit: ' + str(output), flush=True)
        raise


if __name__ == '__main__':
    main()
