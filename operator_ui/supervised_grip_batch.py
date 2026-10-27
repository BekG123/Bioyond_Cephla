"""Supervised plate-present increments to a pre-contact review stop.

Runner owns the batch. Never enables, clears faults, lifts, or changes force
settings. Stops at 5 mm or an anomaly; this does not identify a secure grasp.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean
import time
from uuid import uuid4

from empty_grip_baseline import finite

ROOT = Path(__file__).resolve().parent
BASELINE = ROOT/'demonstrations/empty_grip_baseline/3f0b3a50b5b34bf0a4ff3d3bffc8ddd3.json'
NONCONTACT_REVIEW = ROOT/'demonstrations/supervised_grip/6d16313788984d1383952371c7352c2a_stationary_review.json'
FLOOR = 5.0
SPEED = 5


def selected_reference():
    """Use an explicitly selected, hash-pinned baseline; never guess newest."""
    selection = ROOT/'demonstrations/grip_baseline_selection.json'
    if not selection.exists():
        return BASELINE, BASELINE.read_bytes()
    chosen = json.loads(selection.read_bytes())
    path = (ROOT/'demonstrations'/chosen['path']).resolve()
    expected = (ROOT/'demonstrations/empty_grip_baseline').resolve()
    if (path.parent != expected or path.suffix != '.json' or len(path.stem) != 32
            or any(c not in '0123456789abcdef' for c in path.stem)):
        raise ValueError('Selected empty reference is outside the baseline records.')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != chosen.get('sha256'):
        raise ValueError('Selected empty reference changed; review before closing.')
    references(json.loads(raw))
    return path, raw


def references(baseline):
    if (baseline.get('kind') != 'empty_claw_baseline' or baseline.get('ok') is not True
            or baseline.get('operator_confirmed_empty') is not True
            or baseline.get('plate_present') is True
            or baseline.get('eligible_as_empty_reference') is False
            or baseline.get('speed') != SPEED):
        raise ValueError('Correctly labeled, completed speed-5 empty baseline required.')
    rows = []
    for p in baseline['positions']:
        values = [finite(s['raw_torque']) for s in p['samples']]
        rows.append((finite(p['target_mm']), min(values), max(values)))
    rows.sort()
    # Empirical allowance for observed stationary variation, not a force limit.
    allowance = max(high-low for _, low, high in rows)
    if allowance <= 0:
        raise ValueError('Reference variation unavailable.')
    return rows, allowance


def reference_band(target, rows, allowance):
    lower = max((r for r in rows if r[0] <= target+1e-6), default=None)
    upper = min((r for r in rows if r[0] >= target-1e-6), default=None)
    if lower is None or upper is None:
        raise ValueError('No bracketing empty measurements.')
    if abs(lower[0]-upper[0]) > 1e-6:
        raise ValueError('An exact empty measurement is required at this opening; collect a dense local baseline.')
    return dict(low=min(lower[1], upper[1])-allowance,
                high=max(lower[2], upper[2])+allowance,
                reference_openings_mm=[lower[0], upper[0]],
                exact=abs(lower[0]-upper[0]) < 1e-6)


def labeled_offset(baseline, raw, start):
    """Fixed, operator-labeled noncontact bias; never re-tare during closing."""
    review_raw=NONCONTACT_REVIEW.read_bytes()
    review=json.loads(review_raw)
    if (review.get('operator_confirmed_no_contact') is not True
            or review.get('contact_label')!='no_contact_operator_confirmed'
            or abs(finite(review['e1_mm'])-start)>.001):
        raise ValueError('A no-contact visual label at this exact start is required.')
    batch_id=review['batch_id']
    if len(batch_id)!=32 or any(c not in '0123456789abcdef' for c in batch_id):
        raise ValueError('Invalid labeled trial identifier.')
    trial_raw=(NONCONTACT_REVIEW.parent/(batch_id+'.json')).read_bytes()
    trial=json.loads(trial_raw)
    if (trial.get('baseline_sha256')!=hashlib.sha256(raw).hexdigest()
            or trial.get('start_pose_mm')!=baseline['start_pose_mm']
            or trial.get('status')!='stopped_for_review' or trial.get('ok') is not True
            or abs(finite(trial['final_e1_mm'])-start)>.05):
        raise ValueError('Labeled trial does not match this baseline/pose/opening.')
    samples=review['fresh_stationary_reports']
    if len(samples)<3 or any(s.get('ok') is not True or s.get('telemetry_live') is not True
            or abs(finite(s['e1_position'])-start)>.05 for s in samples):
        raise ValueError('Labeled stationary measurements are incomplete.')
    observed=[finite(s['e1_torque']) for s in samples]
    reference=next(p for p in baseline['positions'] if abs(p['target_mm']-start)<.001)
    empty=mean(finite(s['raw_torque']) for s in reference['samples'])
    return dict(offset=mean(observed)-empty, observed_range=[min(observed),max(observed)],
        review=str(NONCONTACT_REVIEW),review_sha256=hashlib.sha256(review_raw).hexdigest(),
        trial_sha256=hashlib.sha256(trial_raw).hexdigest(),
        assumption='Constant noncontact bias over this bounded trial; stop on any residual departure.',
        force_limit=False, rolling_rebaseline=False)


def run_batch(run, svc, expected_start, joint_band,use_labeled_noncontact=False):
    baseline_path, raw = selected_reference()
    baseline = json.loads(raw)
    refs, allowance = references(baseline)
    start = finite(expected_start)
    if not FLOOR < start <= 28 or abs(start*10-round(start*10)) > 1e-6:
        raise ValueError('Require a reviewed opening on the 0.1 mm grid above 5 mm.')
    targets = [n/10 for n in range(round(start*10)-1, round(FLOOR*10)-1, -1)]
    for target in [start, *targets]:
        reference_band(target, refs, allowance)  # Reject gaps before any motion.
    calibration=labeled_offset(baseline,raw,start) if use_labeled_noncontact else None
    offset=calibration['offset'] if calibration else 0.

    def adjusted_band(target):
        band=reference_band(target,refs,allowance)
        return dict(band,low=band['low']+offset,high=band['high']+offset,
                    raw_empty_low=band['low'],raw_empty_high=band['high'],
                    noncontact_bias=offset)
    joint_band = finite(joint_band)
    if joint_band <= 0:
        raise ValueError('Existing positive joint torque guard required.')
    pose = baseline['start_pose_mm']
    record = dict(schema='cephla.supervised-grip-batch.v1', id=uuid4().hex,
        started_utc=datetime.now(timezone.utc).isoformat(), kind='plate_present_closing_measurement',
        plate_present=True, eligible_as_empty_reference=False, operator_authorized_batch=True,
        authorization='Keep incrementing as the plate is flat. You have my permission to keep incrementing.',
        baseline=str(baseline_path), baseline_sha256=hashlib.sha256(raw).hexdigest(),
        start_pose_mm=pose, start_mm=start, stop_mm=FLOOR, step_mm=.1, speed=SPEED,
        force_limits_changed=False, grasp_verified=False, lift_requested=False,
        empirical_torque_allowance=allowance, joint_torque_guard=joint_band, positions=[])
    record['noncontact_bias_calibration']=calibration
    folder = ROOT/'demonstrations/supervised_grip'
    path = folder/(record['id']+'.json')

    def save():
        folder.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')
        temp.replace(path)

    def check():
        if run.stopped():
            raise ValueError('Operator stopped the batch.')
        refusal = svc._preflight()
        if refusal:
            raise ValueError(refusal)
        actual = svc.pose_mm()
        for key in ('X', 'Y', 'Z', 'Rz'):
            delta = finite(actual[key])-finite(pose[key])
            if key == 'Rz':
                delta = (delta+180)%360-180
            if abs(delta) > .05:
                raise ValueError('Arm moved from the matched baseline pose.')

    def reports(target):
        readings = []
        for _ in range(3):
            check()
            if abs(finite(svc.external_axes()['E1'])-target) > .05:
                raise ValueError('Claw position not stationary at target.')
            report = svc.torque_report(wait_timeout=3)
            if (report.get('ok') is not True or report.get('telemetry_live') is not True
                    or report.get('recovered') or abs(finite(report.get('e1_position'))-target) > .05):
                raise ValueError('Fresh stationary torque report unavailable.')
            readings.append(dict(at_utc=datetime.now(timezone.utc).isoformat(),
                e1_mm=report['e1_position'], raw_torque=finite(report.get('e1_torque')),
                joint_torque={k:finite(report['joints'][k]) for k in ('J1','J2','J3','J4')}))
            check()
        return readings

    def finish(reason):
        record.update(ok=True, status='stopped_for_review', reason=reason,
            finished_utc=datetime.now(timezone.utc).isoformat(),
            final_e1_mm=svc.external_axes()['E1'])
        save()
        run.say(reason)
        return dict(ok=True, status=record['status'], reason=reason, record=str(path),
            increments=len(record['positions']), final_e1_mm=record['final_e1_mm'],
            grasp_verified=False, lift_requested=False)

    try:
        check()
        if abs(finite(svc.external_axes()['E1'])-start) > .02:
            raise ValueError('Starting opening changed; no batch started.')
        save()
        record['initial_samples'] = reports(start)
        if calibration:
            low,high=calibration['observed_range']
            if any(not low-allowance <= s['raw_torque'] <= high+allowance
                   for s in record['initial_samples']):
                return finish('Current readings no longer match the visually clear labeled state; no closing started.')
        initial_band = adjusted_band(start)
        if any(not initial_band['low'] <= s['raw_torque'] <= initial_band['high']
               for s in record['initial_samples']):
            return finish('Initial torque differs from the empty reference; no closing started.')
        initial_joints = {k:mean(s['joint_torque'][k] for s in record['initial_samples'])
                          for k in ('J1','J2','J3','J4')}
        save()
        previous = start
        for index, target in enumerate(targets, 1):
            check()
            if abs(finite(svc.external_axes()['E1'])-previous) > .05:
                raise ValueError('Unexpected claw movement.')
            band = adjusted_band(target)
            record['pending_target_mm'] = target
            save()
            result = svc.move_gripper(target, speed=SPEED, wait_timeout=5)
            record['last_command_result'] = result
            save()
            if result.get('ok') is not True or result.get('recovered') or result.get('gripper_warning'):
                raise ValueError('Increment failed or uncertain; no retry.')
            deadline = time.monotonic()+2
            while abs(finite(svc.external_axes()['E1'])-target) > .05:
                check()
                if time.monotonic() >= deadline:
                    raise ValueError('Claw stalled or did not reach target.')
                time.sleep(.1)
            samples = reports(target)
            record['positions'].append(dict(target_mm=target, samples=samples, reference_band=band))
            record.pop('pending_target_mm', None)
            save()
            for sample in samples:
                if not band['low'] <= sample['raw_torque'] <= band['high']:
                    return finish('Torque differs from the empty reference; inspect before further closing.')
                if any(abs(sample['joint_torque'][k]-initial_joints[k]) > joint_band for k in initial_joints):
                    return finish('Arm torque changed beyond the existing guard; inspect before further closing.')
            previous = target
            if index == 1 or index % 10 == 0 or index == len(targets):
                run.say(f'Supervised closing: E1 {target:.1f} mm; {index}/{len(targets)} increments recorded.')
        return finish('Reached the 5.0 mm pre-contact review stop. No grip acceptance or lift.')
    except Exception as error:
        try:
            record['stop_result'] = svc.program('stop')
        except Exception as stop_error:
            record['stop_error'] = str(stop_error)
        record.update(ok=False, error=str(error), finished_utc=datetime.now(timezone.utc).isoformat())
        save()
        run.state = 'stopped' if run.stopped() else 'error'
        run.say(str(error), 'err')
        return dict(ok=False, error=str(error), record=str(path), grasp_verified=False)
