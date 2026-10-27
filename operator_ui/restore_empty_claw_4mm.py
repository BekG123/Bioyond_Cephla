"""Explicitly confirmed empty-claw restoration through the existing Flask owner."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from execute_alignment_home import api


def run(confirmed):
    if not confirmed:
        raise ValueError("Require plate removed, hands clear and E-stop supervised.")
    before = api('/state')
    anchor = before['robot']['pose_mm']
    record = dict(kind='empty_claw_restore_4mm', plate_present=False,
                  operator_confirmation='Plate removed, hands clear, E-stop supervised',
                  target_mm=4.0, speed=5, before=before, events=[],
                  started_utc=datetime.now(timezone.utc).isoformat(),
                  lift_requested=False, baseline_comparison_applicable=False)
    output = Path(__file__).resolve().parent/'demonstrations/supervised_grip'/(
        'restore_4mm_' + uuid4().hex + '.json')

    def save():
        output.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')

    def check(mode=None, enabled=None, program=None):
        state = api('/state')
        record['events'].append(dict(state=state))
        save()
        r = state['robot']
        if (not r.get('connected') or not r.get('ok') or r.get('errors')
                or state['sequence']['active']
                or r['system_state']['state'] not in
                (('idle', 'enabled', 'running') if program == 'running'
                 else ('idle', 'enabled'))):
            raise RuntimeError('Controller not idle and healthy; no retry.')
        for k in ('X', 'Y', 'Z', 'Rz'):
            d = r['pose_mm'][k] - anchor[k]
            if k == 'Rz':
                d = (d + 180) % 360 - 180
            if not math.isfinite(d) or abs(d) > .05:
                raise RuntimeError('Arm position changed: ' + k)
        if mode and r['control_mode']['mode'] != mode:
            raise RuntimeError('Mode transition not confirmed.')
        if enabled is not None and r['enabled'] != enabled:
            raise RuntimeError('Enable transition not confirmed.')
        if program and r['program_state']['state'] != program:
            raise RuntimeError('Program state not confirmed.')
        return state

    def command(path, body):
        record['events'].append(dict(request=path, body=body))
        save()
        result = api(path, body)
        record['events'].append(dict(response=result))
        save()
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
            raise RuntimeError('Command failed or uncertain: ' + str(result))
        return result

    save()
    changed = False
    try:
        state = check(program='stopped')
        if api('/researcher/api/status')['hand_guiding']['state'] != 'off':
            raise RuntimeError('Hand-guiding is not off.')
        if state['robot']['control_mode']['mode'] not in ('manual', 'auto'):
            raise RuntimeError('Unexpected mode.')
        if state['robot']['control_mode']['mode'] == 'manual' and state['robot']['enabled']:
            raise RuntimeError('Expected disabled Manual or Auto.')
        changed = True
        if state['robot']['control_mode']['mode'] != 'auto':
            command('/mode', dict(mode='auto'))
            state = check(mode='auto', enabled=False, program='stopped')
        if not state['robot']['enabled']:
            command('/enable', dict(confirm=True))
        check(mode='auto', enabled=True, program='stopped')
        command('/program', dict(action='start'))
        state = check(mode='auto', enabled=True, program='running')
        if not state['robot']['lua_app_initialized']:
            raise RuntimeError('Lua not initialized.')
        command('/gripper', dict(action='move', e1=4.0, speed=5))
        deadline = time.monotonic() + 3
        while True:
            state = check(mode='auto', enabled=True, program='running')
            if abs(state['robot']['external_axes']['E1'] - 4.0) <= .02:
                break
            if time.monotonic() > deadline:
                raise RuntimeError('E1 target not confirmed.')
            time.sleep(.15)
        record.update(status='completed', after=state)
    except Exception as error:
        record.update(status='stopped_failed_or_uncertain', error=str(error))
        if changed:
            try:
                record['stop_response'] = api('/program', dict(action='stop'))
            except Exception as stop_error:
                record['stop_error'] = str(stop_error)
    record['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps(dict(path=str(output), status=record['status'],
                         error=record.get('error'), after=record.get('after')), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--empty-confirmed', action='store_true')
    run(parser.parse_args().empty_confirmed)
