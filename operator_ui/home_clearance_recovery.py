"""Cellvis empty-arm recovery between the accepted HOME clearances.

Uses only the released-holder rotation and empty connector already compiled by
the Cellvis workflow. Does not establish calibration, acquire a plate, start
the controller, clear faults, or resume an experiment.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from autonomy import TransferError
from calibration_e2 import accepted
from cellvis24_workflow import compile_steps, evidence, geometry, reference, validate_steps
from cellvis_recovery_handoff import restore_segments
from home_hamilton_exchange import native
from run_record_io import write_run_record
from scope_step_trial import near, preflight
from trajectory_queue import LuaTrajectory

OUTPUT = Path(__file__).parent / 'reports/plate_session/home_clearance_recovery'
SHORT_ANGLE = 90.71661229181757


def snapshot(service, cfg, binding, *, stationary=True, angle=None, pose=None):
    s, n = preflight(service), native(service)
    if stationary and n['moving']:
        raise TransferError('Wait for the arm to stop before HOME recovery.')
    for values, keys in ((s['pose_mm'], ('X', 'Y', 'Z', 'Rz')),
                         (s['joints'], ('J1', 'J2', 'J3', 'J4')),
                         (n['external_axes'], ('E1', 'E2'))):
        if any(type(values.get(k)) not in (int, float) or not math.isfinite(values[k]) for k in keys):
            raise TransferError('HOME recovery requires finite fresh pose, joints and axis feedback.')
    axes = n['external_axes']
    if abs(axes['E1'] - 28) > .07:
        raise TransferError('HOME clearance recovery requires confirmed empty jaws already open to 28 mm.')
    if cfg != binding['cfg'] or {k: list(v) for k, v in service.envelope.items()} != binding['envelope']:
        raise TransferError('HOME recovery geometry/workspace changed.')
    if angle is not None and abs(axes['E2'] - angle) > .1:
        raise TransferError('Holder changed or arrival is uncertain; no retry.')
    if pose is not None:
        near(s['pose_mm'], pose, .05)
    return s, n


def preview(service, cfg):
    binding = geometry()
    acceptance = evidence()
    s, n = snapshot(service, cfg, binding)
    short = dict(reference()['routes']['forward']['start'])
    short['Z'] = round(short['Z'] + 25, 2)
    location = None
    for name, pose in (('hamilton_home_clearance', short), ('long_side_home_clearance', binding['clearance'])):
        try:
            near(s['pose_mm'], pose, .05)
        except TransferError:
            continue
        location = name
        break
    if location is None:
        raise TransferError('No accepted Cellvis HOME-clearance recovery from this measured position.')
    angle = n['external_axes']['E2']
    if not accepted(angle) and abs(angle - SHORT_ANGLE) > .5:
        raise TransferError('Holder is outside the accepted original/Hamilton orientations; inspect its position.')
    # Select the exact empty prefix. Never include descent, gripping or travel.
    prefix = compile_steps(['squid'], 1)[1:3]
    if [s['kind'] for s in prefix] != ['rotate', 'queue'] or prefix[1]['label'] != 'Connect above accepted pickup':
        raise TransferError('Accepted Cellvis empty connector changed.')
    if prefix[0]['target'] != 1.77 or prefix[1]['points'] != [binding['clearance']]:
        raise TransferError('Accepted Cellvis HOME target changed.')
    steps = ([] if accepted(angle) else [prefix[0]])
    if location == 'hamilton_home_clearance':
        steps += [prefix[1]]
    validate_steps(steps, s, cfg, service.envelope)
    return dict(id=uuid4().hex, at=time.time(), dispatch='home_clearance_recovery',
        location_schema=2, executable=True, actions=['move_home'], labels=['Recover HOME clearance'],
        summary='Keep the Cellvis plate seated in HOME, restore the released holder and return the empty arm to long-side HOME clearance.',
        requirements=['Jaws are empty; the lid-off Cellvis P24-1.5H-N plate is seated flat in HOME.',
                      'The unchanged holder sweep and empty connector are clear; hands clear and E-stop supervised.'],
        payload='empty_requires_confirmation', plate='HOME', start=s['pose_mm'], joints=s['joints'],
        axes=n['external_axes'], cfg=deepcopy(cfg), envelope=deepcopy(binding['envelope']),
        acceptance_sha256=acceptance, origin=location, target=binding['clearance'], steps=steps,
        automatic_retries=False, calibration_established=False, experiment_resumed=False)


def verify(service, cfg, approved):
    if not re.fullmatch('[0-9a-f]{32}', approved.get('id', '')):
        raise TransferError('Invalid HOME recovery plan ID.')
    if not 0 <= time.time() - approved['at'] <= 120:
        raise TransferError('HOME recovery preview expired; request a fresh plan.')
    fresh = preview(service, cfg)
    if any(type(approved['start'].get(k)) not in (int, float) or not math.isfinite(approved['start'][k])
           for k in ('X', 'Y', 'Z', 'Rz')):
        raise TransferError('Invalid bound HOME recovery starting pose.')
    near(fresh['start'], approved['start'], .05)
    for field, keys in (('joints', ('J1', 'J2', 'J3', 'J4')), ('axes', ('E1', 'E2'))):
        if any(type(approved[field].get(k)) not in (int, float) or not math.isfinite(approved[field][k])
               or abs(fresh[field][k] - approved[field][k]) > .05 for k in keys):
            raise TransferError('Starting joints/jaws/holder changed; request a fresh HOME recovery.')
    for key in ('cfg', 'envelope', 'acceptance_sha256', 'origin', 'target', 'steps'):
        if fresh[key] != approved[key]:
            raise TransferError('HOME recovery plan changed: ' + key)
    return fresh


def execute(run, service, cfg, approved, empty_jaws=False, plate_seated=False):
    if empty_jaws is not True or plate_seated is not True:
        raise TransferError('Current empty-jaw and seated-Cellvis confirmation required.')
    if run.stopped():
        raise TransferError('HOME recovery stopped before dispatch.')
    fresh = verify(service, cfg, approved)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / (approved['id'] + '.json')
    record = dict(status='checking', plan=approved, payload='operator_confirmed_empty',
        plate='operator_confirmed_seated_HOME', steps=[], motion_sent=False,
        automatic_retries=False, calibration_established=False, experiment_resumed=False)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream)
    def save(): write_run_record(path, record)
    def require(result):
        if result.get('ok') is not True or result.get('recovered') or result.get('gripper_warning'):
            raise TransferError('HOME recovery command failed or uncertain; no retry: ' + str(result))
        return result
    def check(angle=None, stationary=True, pose=None):
        if run.stopped():
            raise TransferError('HOME recovery stopped.')
        return snapshot(service, cfg, fresh, stationary=stationary, angle=angle, pose=pose)
    def dispatch():
        record['motion_sent'] = True
        save()
    def segment(item):
        record['steps'].append(dict(kind='rotate', **item))
        save()
    try:
        check(fresh['axes']['E2'], pose=fresh['start'])
        if fresh['steps']:
            capability = LuaTrajectory(service).capability()
            if not capability.get('available') or capability.get('version') != 220109:
                raise TransferError('Running mixed-speed Lua220109 required; no startup is performed.')
        for step in fresh['steps']:
            check(pose=fresh['start'])
            if step['kind'] == 'rotate':
                restore_segments(run, service, [step['target']], fresh['axes']['E2'],
                    lambda angle: check(angle, pose=fresh['start']), require, dispatch, segment)
                for _ in range(3):
                    _, n = check(1.77, pose=fresh['start'])
                    if not accepted(n['external_axes']['E2']):
                        raise TransferError('Original holder orientation not settled; no connector or retry.')
                    time.sleep(.1)
            else:
                s, n = check(1.77, pose=fresh['start'])
                if not accepted(n['external_axes']['E2']):
                    raise TransferError('Original holder orientation not settled before connector.')
                run.say('Return empty arm along the accepted Cellvis HOME clearance connector.')
                dispatch()
                result = require(LuaTrajectory(service).execute(run, s['pose_mm'], s['joints'],
                    step['points'], cfg, step['speed'], lambda *args: check(1.77, stationary=False),
                    reviewed=True, **step['flags']))
                record['steps'].append(dict(kind='queue', result=result))
                save()
        for _ in range(3):
            s, n = check(1.77, pose=fresh['target'])
            if not accepted(n['external_axes']['E2']):
                raise TransferError('Original holder orientation not verified; no retry.')
            time.sleep(.1)
        record.update(status='completed', final=s, final_native=n)
        return dict(ok=True, record=str(path), pose_mm=s['pose_mm'], holder_angle=n['external_axes']['E2'],
                    plate='HOME', payload='empty', calibration_established=False, experiment_resumed=False)
    except BaseException as error:
        record.update(status='stopped_or_uncertain', error=str(error))
        if record['motion_sent']:
            try: record['stop'] = service.program('stop')
            except Exception as stop: record['stop_error'] = str(stop)
        raise
    finally:
        record['finished_at'] = time.time()
        save()


def start(agent, plan):
    run = agent.get_runner()
    if run.active or run.reserved:
        raise TransferError('Another workflow owns the arm.')
    verify(agent.backend.s, agent.backend.params(), plan)
    with agent.lock:
        if not agent.pending or agent.pending['id'] != plan['id']:
            raise TransferError('HOME recovery approval already consumed.')
        agent.pending = None
        agent.run_meta = dict(name='HOME clearance recovery', total_steps=len(plan['steps']))
        agent.run_state = dict(active=True, step='Recover HOME clearance', done=[], ok=None, error='',
                               message='Restoring HOME with the plate seated and jaws empty.')
    result = run.start('home_clearance_recovery', execute, agent.backend.s, agent.backend.params(), plan, True, True)
    if not result.get('ok'):
        with agent.lock:
            agent.run_state.update(active=False, ok=False, error=result.get('error', 'Recovery did not start.'))
        raise TransferError(result.get('error', 'Recovery did not start.'))
    worker = run._thread
    def finish():
        worker.join()
        state = run.snapshot()
        ok = state.get('state') == 'done' and (state.get('result') or {}).get('ok') is True
        message = ('Empty arm at HOME clearance; holder restored, plate remains in HOME.' if ok else
                   'HOME recovery stopped: ' + str((state.get('result') or {}).get('error', 'completion uncertain')))
        with agent.lock:
            agent.run_state.update(active=False, ok=ok, step=None, done=['HOME restored'] if ok else [],
                                   message=message, error='' if ok else message)
        agent._say('lacry', message)
    threading.Thread(target=finish, daemon=True, name='home-clearance-recovery-result').start()
    return dict(result, message='Restoring the confirmed empty-arm HOME clearance.')
