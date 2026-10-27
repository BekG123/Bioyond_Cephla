"""One authorized 0.1 mm closure, minimum 3.8; no startup or lift."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean
import time
from uuid import uuid4

from supervised_grip_increment import api, validate


def execute(confirmed, start_mm=4.0):
    if not confirmed:
        raise ValueError('Operator confirmation required.')
    if start_mm not in (4.0, 3.9):
        raise ValueError('Only reviewed 4.0 or 3.9 mm starts are supported.')
    target = round(start_mm - .1, 1)
    folder = Path(__file__).resolve().parent/'demonstrations/supervised_grip'
    restoration = folder/'restore_4mm_631f3b5bead14844b24869ee39757abe.json'
    reference = json.loads(restoration.read_text(encoding='utf-8'))
    if reference['status'] != 'completed':
        raise ValueError('Restoration was not completed.')
    pose = reference['after']['robot']['pose_mm']
    before = api('/state')
    r = validate(before, pose)
    if abs(r['external_axes']['E1'] - start_mm) > .02:
        raise ValueError('Expected reviewed starting opening.')
    if api('/researcher/api/status')['hand_guiding']['state'] != 'off':
        raise ValueError('Hand-guiding must be off.')
    record = dict(kind='supervised_plate_present_increment', target_mm=target, speed=5,
                  expected_start_mm=start_mm,
                  plate_present=True, before=before, samples=[],
                  operator_feedback=('Plate replaced; slight visible gap; keep squeezing.'
                                     if start_mm == 4.0 else 'yes still a tiny sliver of a gap'),
                  previous_step=('cdcc8e1f0c774b5ab0fe3cafed7b4ffe.json'
                                 if start_mm == 3.9 else None),
                  operator_confirmed=True, restoration_reference=str(restoration),
                  baseline_comparison_applicable=False, grasp_verified=False,
                  lift_requested=False, started_utc=datetime.now(timezone.utc).isoformat())
    output = folder/(uuid4().hex + '.json')

    def save():
        output.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')

    save()
    sent = False
    try:
        r = validate(api('/state'), pose)
        if abs(r['external_axes']['E1'] - start_mm) > .02:
            raise ValueError('Starting opening changed.')
        record['status'] = 'dispatching_one_increment'
        save()
        sent = True
        result = api('/gripper', dict(action='move', e1=target, speed=5))
        record['command_result'] = result
        save()
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
            raise ValueError('Failed or uncertain increment; no retry.')
        deadline = time.monotonic() + 2
        while abs(validate(api('/state'), pose)['external_axes']['E1'] - target) > .02:
            if time.monotonic() >= deadline:
                raise ValueError('Target not confirmed.')
            time.sleep(.1)
        for _ in range(3):
            report = api('/gripper', dict(action='torque'))
            record['samples'].append(report)
            save()
            if (report.get('ok') is not True or report.get('telemetry_live') is not True
                    or report.get('recovered') or not math.isfinite(report['e1_torque'])
                    or abs(report['e1_position'] - target) > .05):
                raise ValueError('Fresh stationary measurement not confirmed.')
            validate(api('/state'), pose)
        record.update(status='stopped_awaiting_operator_review', after=api('/state'),
                      mean_raw_torque=mean(s['e1_torque'] for s in record['samples']))
    except Exception as error:
        record.update(status='failed_or_uncertain', error=str(error))
        if sent:
            try:
                record['stop_response'] = api('/program', dict(action='stop'))
            except Exception as stop_error:
                record['stop_error'] = str(stop_error)
    record['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps(dict(path=str(output), status=record['status'],
                         error=record.get('error'), mean_raw_torque=record.get('mean_raw_torque'),
                         after=record.get('after')), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator-confirmed', action='store_true')
    parser.add_argument('--start-mm', type=float, choices=(4.0, 3.9), default=4.0)
    args = parser.parse_args()
    execute(args.operator_confirmed, args.start_mm)
