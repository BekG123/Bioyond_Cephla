"""One confirmed 0.1 mm closing step through Flask; no loop, enable or lift."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
import time
from uuid import uuid4

from execute_alignment_home import api

ROOT = Path(__file__).resolve().parent


def validate(state, pose):
    r = state['robot']
    if (state['sequence']['active'] or not r.get('connected') or not r.get('ok')
            or r.get('errors') or not r.get('enabled')
            or r['control_mode']['mode'] != 'auto'
            or r['program_state']['state'] != 'running'):
        raise ValueError('Require idle, healthy, already-running Auto; no reset or enable.')
    for key in ('X', 'Y', 'Z', 'Rz'):
        delta = float(r['pose_mm'][key]) - float(pose[key])
        if key == 'Rz':
            delta = (delta + 180) % 360 - 180
        if not math.isfinite(delta) or abs(delta) > .05:
            raise ValueError('Arm moved from the baseline pose: ' + key)
    return r


def execute(baseline_path, expected_start, confirmed):
    if not confirmed:
        raise ValueError('Operator confirmation required for this one increment.')
    # Target depends on the explicitly reviewed opening, not an arbitrary live reading.
    target = round(expected_start - .1, 3)
    if not math.isfinite(expected_start) or not 3.8 <= target < expected_start <= 28.05:
        raise ValueError('Increment outside the reviewed range.')
    baseline_raw = Path(baseline_path).read_bytes()
    baseline = json.loads(baseline_raw)
    if (baseline.get('kind') != 'empty_claw_baseline' or baseline.get('ok') is not True
            or baseline.get('operator_confirmed_empty') is not True
            or baseline.get('plate_present') is True
            or baseline.get('eligible_as_empty_reference') is False):
        raise ValueError('Require a completed, correctly labeled empty baseline.')
    pose = baseline['start_pose_mm']
    before = api('/state')
    r = validate(before, pose)
    if abs(r['external_axes']['E1'] - expected_start) > .02:
        raise ValueError('Claw opening changed; no increment sent.')
    if api('/researcher/api/status')['hand_guiding']['state'] != 'off':
        raise ValueError('End hand-guiding before this trial.')
    record = dict(schema='cephla.supervised-grip-increment.v1',
        started_utc=datetime.now(timezone.utc).isoformat(),
        baseline=str(baseline_path), baseline_sha256=hashlib.sha256(baseline_raw).hexdigest(),
        plate_present=True, operator_confirmed=True,
        authorization='Plate centered, hands clear, E-stop supervised; one 0.1 mm step.',
        expected_start_mm=expected_start, target_mm=target, speed=5,
        before=before, samples=[], grasp_verified=False, lift_requested=False)
    folder = ROOT/'demonstrations/supervised_grip'
    folder.mkdir(parents=True, exist_ok=True)
    output = folder/(uuid4().hex+'.json')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)

    def save():
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(output)

    sent = False
    try:
        # Recheck after logging and before the only motion request.
        r = validate(api('/state'), pose)
        if abs(r['external_axes']['E1'] - expected_start) > .02:
            raise ValueError('Claw moved before dispatch.')
        sent = True
        result = api('/gripper', dict(action='move', e1=target, speed=5))
        record['command_result'] = result
        save()
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
            raise ValueError('Increment uncertain or failed; no retry.')
        deadline = time.monotonic()+2
        while abs(validate(api('/state'), pose)['external_axes']['E1']-target) > .05:
            if time.monotonic() >= deadline:
                raise ValueError('Target not reached; inspect possible contact or stall.')
            time.sleep(.1)
        for _ in range(3):
            report = api('/gripper', dict(action='torque'))
            record['samples'].append(dict(at_utc=datetime.now(timezone.utc).isoformat(), **report))
            save()
            if (report.get('ok') is not True or report.get('telemetry_live') is not True
                    or report.get('recovered') or not math.isfinite(report['e1_torque'])
                    or abs(report['e1_position']-target) > .05):
                raise ValueError('Fresh stationary torque report not confirmed.')
            validate(api('/state'), pose)
        record['mean_raw_torque'] = mean(s['e1_torque'] for s in record['samples'])
        reference = next((p for p in baseline['positions']
                          if abs(p['target_mm']-target) < .001), None)
        record['matched_empty_reference'] = reference
        record['plate_minus_empty_raw_torque'] = (
            record['mean_raw_torque']-mean(s['raw_torque'] for s in reference['samples'])
            if reference else None)
        record.update(status='stopped_awaiting_operator_review', after=api('/state'))
    except Exception as error:
        record.update(status='failed_or_uncertain', error=str(error))
        if sent:
            try:
                record['stop_response'] = api('/program', dict(action='stop'))
            except Exception as stop_error:
                record['stop_error'] = str(stop_error)
        save()
        raise
    record['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps(dict(record=str(output), status=record['status'], target_mm=target,
        actual_mm=record['after']['robot']['external_axes']['E1'],
        mean_raw_torque=record['mean_raw_torque'],
        matched_empty_reference=reference is not None,
        plate_minus_empty_raw_torque=record['plate_minus_empty_raw_torque'],
        grasp_verified=False, lift_requested=False), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline')
    parser.add_argument('--start-mm', type=float, required=True)
    parser.add_argument('--operator-confirmed', action='store_true')
    args = parser.parse_args()
    execute(args.baseline, args.start_mm, args.operator_confirmed)
