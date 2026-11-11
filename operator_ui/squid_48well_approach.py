"""Repeatable, explicitly confirmed loaded Home -> above Squid. No seating/release."""
from copy import deepcopy
import json
import math
import time
from uuid import uuid4

from autonomy import TransferError
from projected_pickup import ROOT, load, accepted_grip
from scope_step_trial import preflight, near
from scope_compact137 import HoldingService
from squid_48well_higher_route import reference, SHA
from squid_48well_endpoint_trial import check_route
from trajectory_queue import LuaTrajectory, travel_program_blocker

FOLDER = ROOT/'operator_ui/reports/squid_48well_approach'


def review(service, cfg):
    state = preflight(service)
    plan, path = reference()
    near(state['pose_mm'], path[0], .05)
    points = path[1:-1]  # Deliberately excludes the seating descent.
    check_route(path[0], points, state['joints'], cfg, service.envelope, 'raised_transit')
    profile, digest = load()
    if not accepted_grip(profile):
        raise TransferError('Accepted 48-well grip reference required.')
    e1 = state.get('external_axes', {}).get('E1')
    if type(e1) not in (float, int) or not math.isfinite(e1) or not 3.85 <= e1 <= 3.95:
        raise TransferError('Expected held 48-well plate with grip near 3.9 mm.')
    blocker = travel_program_blocker(LuaTrajectory(service).capability(), 137)
    if blocker:
        raise TransferError(blocker)
    return deepcopy(dict(candidate_sha256=SHA, profile_sha256=digest, start=path[0],
                         points=points, joints=state['joints'], e1=e1, cfg=cfg,
                         envelope=plan['envelope'], speed=137))


def execute(run, service, cfg, approved):
    fresh = review(service, cfg)
    for key in ('candidate_sha256', 'profile_sha256', 'start', 'points', 'cfg', 'envelope', 'speed'):
        if fresh[key] != approved[key]:
            raise TransferError('Approach changed after review.')
    if abs(fresh['e1']-approved['e1']) > .05 or any(
            abs(fresh['joints'][k]-approved['joints'][k]) > .5 for k in fresh['joints']):
        raise TransferError('Start feedback changed after review.')
    if run.stopped():
        raise TransferError('Stopped before approach.')
    FOLDER.mkdir(parents=True, exist_ok=True)
    output = FOLDER/(uuid4().hex+'.json')
    record = dict(status='started', started_at=time.time(), plan=fresh, samples=[],
                  authorization='Operator confirmed held plate, clear Home-to-above-Squid route and on-site emergency-stop supervision. Approach only.',
                  lowering_executed=False, release_executed=False, gripper_commands=False)
    def save():
        output.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')
    save()
    holding = HoldingService(service, fresh['e1'], fresh['envelope'])
    try:
        run.say('Following the existing raised Squid approach; stopping above the holder with grip unchanged.')
        def progress(stage, done, total):
            record['samples'].append(dict(at=time.time(), stage=stage, done=done,
                                          total=total, robot=service.status()))
            save()
        result = LuaTrajectory(holding).execute(run, fresh['start'], fresh['joints'],
            fresh['points'], cfg, fresh['speed'], progress, reviewed=True,
            scope_trial=True, scope_speed137=True, scope_phase='raised_transit')
        if not result.get('ok'):
            raise TransferError('Approach completion uncertain; no retry.')
        state = preflight(holding)
        near(state['pose_mm'], fresh['points'][-1], .1)
        record.update(status='completed_above_squid', result=result)
        run.say('Above Squid. Stopped before lowering or release.', 'good')
        return dict(ok=True, record=str(output), pose_mm=state['pose_mm'],
                    lowering_executed=False, release_executed=False)
    except Exception as error:
        record.update(status='stopped_or_failed', error=str(error))
        try:
            record['stop_response'] = service.program('stop')
        except Exception as stop_error:
            record['stop_error'] = str(stop_error)
        raise
    finally:
        record['finished_at'] = time.time()
        save()
        run.audit('squid_48well_approach', record=str(output), status=record['status'])
