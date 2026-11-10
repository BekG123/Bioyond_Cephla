"""Holder-only commissioning through the console's single robot owner."""
import json
import hashlib
import math
from pathlib import Path
import secrets
import time
from draggo import DragGoRPC

ROOT = Path(__file__).resolve().parent / 'reports/holder_short_side'
HOME = dict(X=289.97, Y=62.63, Z=248.02, Rz=-3.88)
FAST_SPEED = 137
FAST_PROTOCOL, FAST_PROBE_MODE, FAST_MOVE_MODE = 250104, 13, 14


def check_snapshot(state, native, expected_e2=None):
    if (not state.get('ok') or not state.get('connected') or state.get('errors')
            or not state.get('enabled') or state['control_mode']['mode'] != 'auto'
            or state['program_state']['state'] != 'running'):
        raise ValueError('Holder trial requires healthy running Auto; no automatic startup.')
    if any(native.get(k, True) for k in ('moving', 'error', 'emergency', 'drag', 'manual')):
        raise ValueError('Holder trial requires stationary automatic control.')
    for key, value in HOME.items():
        actual = state['pose_mm'][key]
        if not math.isfinite(actual) or abs(actual-value) > .2:
            raise ValueError('Holder rotation is commissioned only with the arm at Home.')
    if native.get('external_units', {}).get('E2') != 'degrees':
        raise ValueError('E2 angular feedback unavailable')
    axes = native['external_axes']
    if any(not math.isfinite(v) for v in axes.values()):
        raise ValueError('Invalid external-axis feedback')
    if expected_e2 is None:
        if not -5 <= axes['E2'] <= 5:
            raise ValueError('Direction probe requires E2 near its original orientation.')
    elif not math.isfinite(expected_e2) or abs(axes['E2']-expected_e2) > .05:
        raise ValueError('Holder changed since its recorded direction test.')
    if abs(axes['E1']) > .5:
        raise ValueError('Direction probe expects empty closed jaws at Home.')


def snapshot(service, expected_e2=None):
    s = service.status()
    n = DragGoRPC(service._endpoint_addr()[0]).info()
    check_snapshot(s, n, expected_e2)
    return dict(robot=s, native=n)


def quarter_turn_target(probe, confirmed_ccw):
    if (confirmed_ccw is not True or probe.get('status') != 'completed_awaiting_direction'
            or probe.get('result', {}).get('ok') is not True):
        raise ValueError('Successful probe and explicit CCW observation required.')
    origin = probe['origin_degrees']
    actual = probe['after']['native']['external_axes']['E2']
    if (not all(math.isfinite(v) for v in (origin,actual))
            or abs(probe['target_degrees']-origin-5) > 1e-6
            or abs(actual-probe['target_degrees']) > .1):
        raise ValueError('Invalid direction-probe evidence')
    return actual, origin+90


def verified_return():
    restored = ROOT/'fast_start_restore.json'
    if restored.exists():
        raw = restored.read_bytes()
        record = json.loads(raw)
        probe = json.loads((ROOT/'direction_probe.json').read_text())
        if (record.get('status') != 'fast_start_restored' or not record.get('result', {}).get('ok')
                or abs(record['target_degrees']-probe['origin_degrees']) > 1e-6):
            raise ValueError('Fast-test start restoration did not verify')
        return raw, record
    raw = (ROOT/'return_original.json').read_bytes()
    prior = json.loads(raw)
    if prior.get('status') == 'original_restored' and prior.get('result', {}).get('ok'):
        return raw, prior
    verification_raw = (ROOT/'return_original_verified.json').read_bytes()
    verification = json.loads(verification_raw)
    if (verification.get('status') != 'original_restored_by_readback'
            or verification.get('result', {}).get('ok') is not True
            or verification.get('original_attempt_sha256') != hashlib.sha256(raw).hexdigest()
            or verification.get('target_degrees') != prior.get('target_degrees')
            or verification.get('motion_resent') is not False):
        raise ValueError('Return verification does not match the original attempt')
    return verification_raw, verification


def direction_probe(run, service, *, quarter=False, confirmed_ccw=False, return_original=False, fast=False, restore_test=False):
    """Probe, or finish a total quarter turn bound to the completed probe."""
    ROOT.mkdir(parents=True, exist_ok=True)
    if sum((quarter, return_original, fast, restore_test)) > 1:
        raise ValueError('Choose exactly one rotation operation')
    label = 'fast_start_restore' if restore_test else 'return_original' if return_original else 'fast_quarter_turn' if fast else 'quarter_turn' if quarter else 'direction_probe'
    path = ROOT/(label+'.json')
    if path.exists():
        raise ValueError('Direction probe already attempted; review its receipt before another move.')
    evidence = {}
    expected = None
    if quarter or return_original or fast or restore_test:
        raw = (ROOT/'direction_probe.json').read_bytes()
        probe = json.loads(raw)
        expected, target = quarter_turn_target(probe, confirmed_ccw)
        evidence = dict(probe_sha256=hashlib.sha256(raw).hexdigest(),
            operator_observation='User confirmed positive E2 test turned counterclockwise.',
            original_e2_degrees=probe['origin_degrees'])
        if return_original or fast:
            if fast:
                prior_raw, prior = verified_return()
            else:
                prior_raw = (ROOT/'quarter_turn.json').read_bytes()
                prior = json.loads(prior_raw)
            allowed = ('original_restored','original_restored_by_readback','fast_start_restored') if fast else ('quarter_turn_completed',)
            if prior.get('status') not in allowed or not prior.get('result', {}).get('ok'):
                raise ValueError('Previous rotation has no verified completion')
            expected = prior['after']['native']['external_axes']['E2']
            if abs(expected-prior['target_degrees']) > .1:
                raise ValueError('Previous rotation did not reach its target')
            target = probe['origin_degrees'] + (90 if fast else 0)
            evidence.update(previous_receipt_sha256=hashlib.sha256(prior_raw).hexdigest())
            if fast:
                evidence['plate_retained_operator_confirmed'] = True
        if restore_test:
            startup_raw = (ROOT/'fast137_startup.json').read_bytes()
            startup = json.loads(startup_raw)
            expected = startup['after_native']['external_axes']['E2']
            target = probe['origin_degrees']
            if not math.isfinite(expected) or abs(expected-target) > .5:
                raise ValueError('Start restoration exceeds the reviewed half-degree correction')
            evidence['startup_sha256'] = hashlib.sha256(startup_raw).hexdigest()
    before = snapshot(service, expected)
    origin = before['native']['external_axes']['E2']
    if not (quarter or return_original or fast or restore_test):
        target = origin+5
    if not 0 < abs(target-origin) <= 90.01:
        raise ValueError('Invalid remaining quarter turn')
    record = dict(status='prepared', before=before, origin_degrees=origin,
                  target_degrees=target, requested_final_direction='counterclockwise',
                  direction_verified=quarter or return_original or fast or restore_test, at=time.time(), motion_sent=False,
                  speed_setting=FAST_SPEED if fast else 1, **evidence)
    with path.open('x', encoding='utf-8') as f:
        json.dump(record, f, indent=2)

    def save():
        path.write_text(json.dumps(record, indent=2), encoding='utf-8')

    def command():
        current = snapshot(service, origin)
        if abs(current['native']['external_axes']['E2']-origin) > .05 or run.stopped():
            raise ValueError('Holder changed or stop requested before probe.')
        token = secrets.randbelow(1000000)+1
        response = service._hostpoint({7: float(token)}, FAST_PROBE_MODE if fast else 9, 5)
        record['capability_response'] = response
        if not response.get('ok'):
            raise ValueError(response.get('error', 'Capability probe failed'))
        registers = service.robot.get_sys_var_i([7, 8])
        record['capability_registers'] = registers
        if registers.get(7) != token or registers.get(8) != (FAST_PROTOCOL if fast else 250102):
            raise ValueError('Published holder interface not verified; no rotation sent.')
        if run.stopped():
            raise ValueError('Stopped before rotation')
        record.update(status='moving', motion_sent=True)
        save()
        record['command_started_at'] = time.time()
        started = time.monotonic()
        result = service._hostpoint({7: float(token), 8: origin, 9: target}, FAST_MOVE_MODE if fast else 10, 120 if quarter or return_original else 30)
        record['command_elapsed_s'] = time.monotonic()-started
        record['motion_result'] = result
        if not result.get('ok'):
            raise ValueError(result.get('error', 'Unknown rotation completion; do not retry.'))
        n = DragGoRPC(service._endpoint_addr()[0]).info()
        s = service.status()
        record['after'] = dict(robot=s, native=n)
        if run.stopped() or s.get('errors') or any(n.get(k, True) for k in ('moving','error','emergency','drag')):
            raise ValueError('Rotation finished with uncertain controller state.')
        if abs(n['external_axes']['E2']-target) > .1:
            raise ValueError('Holder arrival mismatch')
        for key in HOME:
            if abs(s['pose_mm'][key]-before['robot']['pose_mm'][key]) > .1:
                raise ValueError('Arm changed during holder-only rotation')
        for key, value in before['native']['external_axes'].items():
            if key != 'E2' and abs(n['external_axes'][key]-value) > .05:
                raise ValueError('Another external axis changed during holder-only rotation')
        return dict(ok=True, actual_e2=n['external_axes']['E2'], report=str(path),
                    awaiting='Fast rotation package publication' if return_original else 'New short-side pickup alignment' if quarter or fast else 'Operator observation of clockwise or counterclockwise direction')

    try:
        result = service._locked(command)
        if not result.get('ok'):
            raise ValueError(result.get('error', 'Motion lock unavailable'))
        status = 'fast_start_restored' if restore_test else 'original_restored' if return_original else 'fast_quarter_turn_completed' if fast else 'quarter_turn_completed' if quarter else 'completed_awaiting_direction'
        record.update(status=status, result=result)
        run.say('Holder rotation complete. Arm and claw remained stationary.')
        return result
    except Exception as error:
        record.update(status='failed_or_uncertain', error=str(error))
        raise
    finally:
        record['finished_at'] = time.time()
        save()
