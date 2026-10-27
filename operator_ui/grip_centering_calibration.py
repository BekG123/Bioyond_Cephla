"""Authorized calibration and Align only; preserve images, state and sequence logs."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from review_grip_centering_retreat import api


def main():
    if sys.argv[1:] not in (['--operator-confirmed'], ['--operator-confirmed', '--from-home'],
                           ['--operator-confirmed', '--from-config-stop']):
        raise RuntimeError('Operator confirmation required.')
    from_home = '--from-home' in sys.argv
    from_stop = '--from-config-stop' in sys.argv
    folder = Path(__file__).parent / 'reports/grip_centering' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    log = dict(status='preflight', started_at=time.time(), grip_requested=False,
               authorization=('Operator returned arm to Home and explicitly requested restarting full calibration; Grip remains off.'
                              if from_home else
                              'Operator authorized fresh calibration and Align after open-jaw vertical retreat.'),
               observations=[], commands=[])
    output = folder / 'calibration_align.json'
    current = None

    def save():
        output.write_text(json.dumps(log, indent=2, allow_nan=False), encoding='utf-8')

    def healthy():
        state = api('/state')
        robot = state['robot']
        if (not robot.get('ok') or robot.get('errors') or not robot.get('enabled')
                or robot['control_mode']['mode'] != 'auto'
                or robot['program_state']['state'] != 'running'):
            raise RuntimeError('Healthy already-running Auto required; no automatic reset or enable.')
        if not 27.95 <= robot['external_axes']['E1'] <= 28.1:
            raise RuntimeError('Jaws must remain fully open.')
        return state

    def start(path, body, name):
        nonlocal current
        current = name
        event = dict(at=time.time(), path=path, request=body)
        log['commands'].append(event)
        save()
        event['response'] = api(path, body)
        save()
        if not event['response'].get('ok'):
            raise RuntimeError(str(event['response']))
        deadline = time.monotonic() + 300
        last = None
        while True:
            state, seq = healthy(), api('/seq')
            log['observations'].append(dict(at=time.time(), state=state, sequence=seq))
            save()
            if seq['name'] != name:
                raise RuntimeError('Another sequence replaced this trial.')
            if seq.get('log'):
                message = seq['log'][-1]['msg']
                if message != last:
                    print(message, flush=True)
                    last = message
            if not seq['active']:
                if seq['state'] != 'done' or (seq.get('result') or {}).get('ok') is not True:
                    raise RuntimeError(str(seq.get('result')))
                return seq
            if time.monotonic() > deadline:
                raise RuntimeError('Observation deadline reached; stop for review, no retry.')
            time.sleep(.5)

    def capture(name):
        before = healthy()
        with urlopen('http://127.0.0.1:5002/frame', timeout=15) as response:
            data = response.read()
        after = healthy()
        if after['camera'].get('error') or not after['camera'].get('open') or after['camera']['age_s'] > 1:
            raise RuntimeError('Fresh camera image unavailable.')
        if any(abs(after['robot']['pose_mm'][k] - before['robot']['pose_mm'][k]) > .05
               for k in ('X', 'Y', 'Z', 'Rz')):
            raise RuntimeError('Camera capture pose changed.')
        (folder / (name + '.jpg')).write_bytes(data)
        log[name] = dict(before=before, after=after, image=str(folder / (name + '.jpg')))
        save()

    try:
        state = healthy()
        log['before'] = state
        if state['sequence']['active']:
            raise RuntimeError('Require idle robot.')
        if api('/researcher/api/status')['hand_guiding']['state'] != 'off':
            raise RuntimeError('Hand guiding must be off.')
        if from_home:
            points = json.loads((Path(__file__).parent / 'points.json').read_text(encoding='utf-8-sig'))
            home = points['points'][points['roles']['home']]
            expected = dict(X=home['x'], Y=home['y'], Z=home['z_grip'], Rz=home['rz'])
            if any(abs(state['robot']['pose_mm'][k] - v) > .1 for k, v in expected.items()):
                raise RuntimeError('Arm is not at saved Home.')
            log['verified_home'] = expected
        elif from_stop:
            previous_path = Path(__file__).parent / 'reports/grip_centering/20261020T063152894916Z/calibration_align.json'
            previous = json.loads(previous_path.read_text())
            stopped = previous['observations'][-1]
            if stopped['sequence']['state'] != 'stopped' or stopped['sequence']['name'] != 'find_disk':
                raise RuntimeError('Expected explicitly stopped configuration-selection trial.')
            expected = stopped['state']['robot']['pose_mm']
            if any(abs(state['robot']['pose_mm'][k] - expected[k]) > .1 for k in ('X','Y','Z','Rz')):
                raise RuntimeError('Arm changed from the recorded configuration stop.')
            log['configuration_stop'] = str(previous_path)
        elif abs(state['robot']['pose_mm']['Z'] - 300) > .1:
            raise RuntimeError('Require stationary reviewed retreat endpoint at Z300.')
        log['camera_resume'] = api('/camera/resume', {})
        capture('before_calibration')
        draft = api('/researcher/api/status')['draft']
        log['calibration'] = start('/researcher/api/workflow/Calibrate',
                                  dict(ready=True, draft_id=draft['id'], revision=draft['revision']),
                                  'researcher_calibrate')
        target = api('/state')['target']
        if not target or target.get('config') != 'Wide' or target.get('converged') is not True:
            raise RuntimeError('Converged Wide target required.')
        capture('calibrated')
        draft = api('/researcher/api/status')['draft']
        log['alignment'] = start('/researcher/api/workflow/Align',
                                dict(ready=True, draft_id=draft['id'], revision=draft['revision']),
                                'researcher_align')
        capture('aligned')
        log.update(status='completed', finished_at=time.time(), after=healthy())
        save()
        print(json.dumps(dict(record=str(output), target=target,
                              pose=log['after']['robot']['pose_mm']), indent=2))
    except Exception as error:
        log.update(status='failed_or_uncertain', error=str(error), finished_at=time.time())
        if current:
            try:
                seq = api('/seq')
                if seq.get('active') and seq.get('name') == current:
                    log['stop_response'] = api('/seq/stop', {})
            except Exception as stop_error:
                log['stop_error'] = str(stop_error)
        save()
        print('Stopped without retry: ' + str(output), flush=True)
        raise


if __name__ == '__main__':
    main()
