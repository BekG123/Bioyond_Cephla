"""Cellvis commissioning: rotate the released holder and inspect open short-side jaws.

This is deliberately separate from the accepted 48-well handling receipts.
No grip, loaded transfer, instrument operation, fault reset or automatic retry.
"""
import hashlib
import json
import math
from pathlib import Path
import secrets
import time

from autonomy import TransferError, check_path
from calibration_e2 import accepted
from home_hamilton_exchange import native
from scope_step_trial import near, preflight
from short_side_hover_transfer import reference
from trajectory_queue import LuaTrajectory
from run_record_io import write_run_record

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'operator_ui/reports/plate_session/cellvis24_validation'
PROFILE = ROOT / 'Pick and Hold/Calibration/plate_profiles/cellvis_p24_1_5h_n.json'
SOURCE = FOLDER / 'calibration_finish.json'
OUTPUT = FOLDER / 'short_side_open_trial.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate(profile, short):
    """Height hypothesis only; short-side geometry still needs visual inspection."""
    height_delta = profile['handling']['descent_pose_mm']['Z'] - 73.718
    if not math.isfinite(height_delta) or abs(height_delta) > 5:
        raise TransferError('Unexpected Cellvis height adjustment.')
    seat = dict(short['descent_endpoint'])
    seat['Z'] = round(seat['Z'] + height_delta, 3)
    return dict(seat=seat, hover=dict(seat, Z=seat['Z'] + 30),
                height_delta_mm=height_delta, holder_angle=short['holder_e2_degrees'])


def plan(service, cfg):
    if OUTPUT.exists():
        raise TransferError('Cellvis short-side trial already attempted; inspect its receipt before another attempt.')
    profile = json.loads(PROFILE.read_bytes())
    source = json.loads(SOURCE.read_bytes())
    h = profile['handling']
    if (profile['id'] != 'cellvis_p24_1_5h_n' or not h['proof_lift_accepted']
            or not h['candidate_proof_lift']['operator_retention_acceptance']['accepted']
            or source['status'] != 'calibration_finish_completed_plate_released_in_HOME'):
        raise TransferError('Accepted Cellvis long-side pickup and completed HOME release required.')
    parent, _, short = reference('04')
    if cfg != parent['config']:
        raise TransferError('Robot IK configuration differs from the accepted route.')
    state = preflight(service)
    n = native(service)
    if (n['moving'] or not all(math.isfinite(n['external_axes'][k]) for k in ('E1','E2'))
            or abs(n['external_axes']['E1'] - 28) > .07 or not accepted(n['external_axes']['E2'])):
        raise TransferError('Released jaws at 28 mm and original holder orientation required.')
    start = source['after']['robot']['pose_mm']
    near(state['pose_mm'], start, .05)
    g = candidate(profile, short)
    if abs(g['holder_angle'] - n['external_axes']['E2']) > 90.01:
        raise TransferError('Holder rotation exceeds the published segment limit.')
    q = check_path(start, g['hover'], state['joints'], cfg, service.envelope)
    check_path(g['hover'], g['seat'], q, cfg, service.envelope)
    capability = LuaTrajectory(service).capability()
    if not capability.get('available'):
        raise TransferError('Published Lua queue unavailable.')
    return dict(start=state['pose_mm'], joints=state['joints'], geometry=g,
                e2=n['external_axes']['E2'], cfg=cfg,
                envelope={k:list(v) for k,v in service.envelope.items()},
                profile_sha256=digest(PROFILE), source_sha256=digest(SOURCE),
                speed=5, grip=False, transfer=False, stop_before_grip=True,
                basis='48-well short-side XY/yaw with Cellvis long-side height difference; first supervised fit inspection, not accepted short-side pickup.')


def execute(run, service, cfg, approved):
    fresh = plan(service, cfg)
    for key in ('geometry', 'cfg', 'envelope', 'profile_sha256', 'source_sha256', 'speed', 'stop_before_grip'):
        if approved.get(key) != fresh[key]:
            raise TransferError('Cellvis trial changed after planning: ' + key)
    near(fresh['start'], approved['start'], .05)
    if abs(fresh['e2']-approved['e2']) > .05 or any(abs(fresh['joints'][k]-approved['joints'][k]) > .1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Starting arm/holder configuration changed.')
    record = dict(status='started', plan=fresh, steps=[], samples=[], motion_sent=False,
                  operator_statement='All station conditions confirmed; requested Cellvis Hamilton then Squid workflow.',
                  short_side_grip_accepted=False)
    with OUTPUT.open('x', encoding='utf-8') as f:
        json.dump(record, f, indent=2)
    def save():
        write_run_record(OUTPUT, record)
    expected_e2 = fresh['e2']
    def check(stationary=False):
        s = preflight(service); n = native(service)
        if run.stopped() or (stationary and n['moving']):
            raise TransferError('Trial stopped or arm not stationary.')
        if (not all(math.isfinite(n['external_axes'][k]) for k in ('E1','E2'))
                or abs(n['external_axes']['E1']-28) > .07 or abs(n['external_axes']['E2']-expected_e2) > .1):
            raise TransferError('Jaw or holder feedback changed.')
        record['samples'].append(dict(at=time.time(), pose=s['pose_mm'], axes=n['external_axes']))
        save()
        return s, n
    try:
        run.say('Cellvis: rotate released holder; jaws remain open at 28 mm.')
        def rotate():
            before, _ = check(True)
            token = secrets.randbelow(1000000)+1
            probe = service._hostpoint({7:float(token)}, 13, 5)
            if not probe.get('ok') or probe.get('recovered'):
                raise TransferError('Holder capability probe uncertain.')
            regs = service.robot.get_sys_var_i([7,8])
            if regs != {7:token, 8:250104}:
                raise TransferError('Holder interface mismatch.')
            check(True)
            record['motion_sent'] = True; save()
            result = service._hostpoint({7:float(token),8:fresh['e2'],9:fresh['geometry']['holder_angle']},14,120)
            if not result.get('ok') or result.get('recovered'):
                raise TransferError('Holder rotation uncertain; no retry.')
            near(service.pose_mm(), before['pose_mm'], .05)
            return result
        record['rotation'] = service._locked(rotate)
        if not record['rotation'].get('ok'):
            raise TransferError('Holder rotation did not complete.')
        expected_e2 = fresh['geometry']['holder_angle']
        for _ in range(3):
            check(True); time.sleep(.1)
        for label, goal in [('Open-jaw alignment above rotated Cellvis', fresh['geometry']['hover']),
                            ('Slow first Cellvis short-side descent; stop before grip', fresh['geometry']['seat'])]:
            run.say(label)
            s, _ = check(True)
            check_path(s['pose_mm'], goal, s['joints'], cfg, service.envelope)
            item = dict(label=label, target=goal, status='dispatching'); record['steps'].append(item); save()
            result = LuaTrajectory(service).execute(run,s['pose_mm'],s['joints'],[goal],cfg,5,
                                                    lambda *args:check(),reviewed=True)
            if not result.get('ok') or result.get('recovered'):
                raise TransferError('Cellvis open-jaw move uncertain; no retry.')
            after, _ = check(True); near(after['pose_mm'], goal, .05)
            item.update(status='completed', response=result); save()
        record.update(status='open_short_side_at_candidate_pending_inspection', final=after)
        return dict(ok=True, record=str(OUTPUT), pose_mm=after['pose_mm'], grip=False, inspection_required=True)
    except Exception as error:
        record.update(status='failed_or_uncertain', error=str(error))
        if record['motion_sent']:
            try: record['stop_response'] = service.program('stop')
            except Exception as stop_error: record['stop_error'] = str(stop_error)
        raise
    finally:
        record['finished_at'] = time.time(); save()
