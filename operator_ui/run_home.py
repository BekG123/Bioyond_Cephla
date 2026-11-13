"""Return the EMPTY arm to HOME holder clearance, not IDLE.

Default: read-only route preview. --execute --empty-gripper confirms empty/free
jaws, a clear connector and jaw-closing sweep, arm released, hands clear and
E-stop supervised. Uses the existing checked near-HOME connector at speed 5:
cross/turn at the current height, then lower above HOME. It does not descend
to seat a plate, release a payload, rotate the holder, or run calibration.
Execution connects the console once if disconnected. Requires running Auto;
no Lua startup, fault reset or automatic motion retry. Starts
outside the existing near-HOME area need a saved preview supplied with
--reviewed-plan. That flag confirms the exact empty-arm sweep is physically
clear; IK alone cannot establish rack clearance. Never use it while caught.
"""
import argparse
import json
import math
import time
from pathlib import Path
from uuid import uuid4

from run_cellvis24_workflow import api
from run_hotel_slot_trial import connector as near_home_connector
from hotel_slot1_delivery import geometry, check_geometry
from scope_step_trial import near
from run_record_io import write_run_record

REPORTS = Path(__file__).resolve().parent/'reports/plate_session/home_returns'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Run the previewed type of route with fresh state checks.')
    parser.add_argument('--empty-gripper', action='store_true', help='Confirm there is no plate or other payload between the jaws.')
    parser.add_argument('--reviewed-plan', type=Path, help='Saved HOME preview JSON: confirms arm is free and the exact route/jaw sweep is clear. Required outside the existing near-HOME area.')
    args = parser.parse_args(argv)
    if args.execute and not args.empty_gripper:
        parser.error('--execute requires --empty-gripper; jaw position cannot establish payload state.')
    return args


def in_near_home(p):
    return (290<=p['X']<=335 and -80<=p['Y']<=35 and
            105<=p['Z']<=300 and 0<=p['Rz']<=100)


def connector(robot, g):
    p = robot['pose_mm']
    if in_near_home(p):
        return near_home_connector(robot, g)
    if not all(math.isfinite(p[k]) for k in ('X','Y','Z','Rz')):
        raise RuntimeError('Invalid starting pose.')
    if p['Z'] < g['home']['Z']:
        raise RuntimeError('Start below HOME clearance needs a station-specific retreat; no automatic rise near fixtures.')
    # A candidate, not a collision-free claim. Keep height until above HOME.
    points = [dict(g['home'], Z=p['Z']), dict(g['home'])]
    validation = check_geometry(p, points, robot['joints'], g['cfg'], g['envelope'])
    quantized = [{k:round(point[k],2) for k in ('X','Y','Z','Rz')} for point in points]
    check_geometry(p, quantized, robot['joints'], g['cfg'], g['envelope'])
    return quantized, validation


def validate_review(saved, current):
    if saved.get('schema') != 'empty-home-connector-v1' or saved.get('destination') != 'HOME':
        raise RuntimeError('Not a HOME connector preview.')
    if not 0 <= time.time()-saved.get('at',0) <= 600:
        raise RuntimeError('HOME preview expired; make and review a fresh preview.')
    near(current['start'], saved['start'], .05)
    if any(abs(current['start_joints'][k]-v)>.1 for k,v in saved['start_joints'].items()):
        raise RuntimeError('Joints changed since HOME preview.')
    for key in ('points','endpoint','speed','cfg','envelope'):
        if current[key] != saved[key]:
            raise RuntimeError('HOME route/configuration changed; make a fresh preview.')


def checked_state(*, connect_if_needed=False):
    state = api('state')
    if not state['robot'].get('connected') and connect_if_needed:
        if state.get('sequence', {}).get('active'):
            raise RuntimeError('Console disconnected while a sequence is active; not reconnecting during a run.')
        api('connect', {'ip':'192.168.201.220'})
        state = api('state')
    robot = state['robot']
    if not robot.get('connected'):
        raise RuntimeError('Console disconnected from the arm. Execution attempts one connection before checking the route; preview does not connect. No motion started.')
    blockers = []
    if not robot.get('ok'): blockers.append('robot status read failed: '+str(robot.get('error','unknown')))
    if robot.get('errors'): blockers.append('controller faults: '+str(robot['errors']))
    if not robot.get('enabled'): blockers.append('servos disabled')
    if robot.get('moving', False): blockers.append('arm moving')
    mode = robot.get('control_mode', {}).get('mode')
    program = robot.get('program_state', {}).get('state')
    if mode != 'auto': blockers.append('mode='+str(mode)+' (Auto required)')
    if program != 'running': blockers.append('Lua program='+str(program)+' (running required)')
    if not state.get('envelope', {}).get('enabled'): blockers.append('workspace checks disabled')
    if state.get('sequence', {}).get('active'): blockers.append('another sequence active')
    if blockers:
        raise RuntimeError('HOME return blocked: '+'; '.join(blockers)+'. No fault reset or Lua startup attempted.')
    seq = api('seq')
    if seq.get('active'):
        raise RuntimeError('Another sequence is active.')
    from draggo import DragGoRPC
    native = DragGoRPC('192.168.201.220').info()
    if any(native.get(k, True) for k in ('moving', 'error', 'emergency', 'drag', 'manual')):
        raise RuntimeError('Native controller state does not permit the empty HOME return.')
    if not math.isfinite(native['external_axes']['E1']):
        raise RuntimeError('Invalid gripper feedback.')
    return state, native


def main(argv=None):
    args = parse_args(argv)
    state, native = checked_state(connect_if_needed=args.execute)
    g = geometry()
    points, validation = connector(state['robot'], g)
    plan = dict(schema='empty-home-connector-v1', at=time.time(), destination='HOME', endpoint=g['home'], start=state['robot']['pose_mm'],
                start_joints=state['robot']['joints'], cfg=g['cfg'], envelope=g['envelope'],
                points=points, speed=5, validation=validation,
                start_area=dict(X=[290,335], Y=[-80,35], Z=[105,300], Rz=[0,100]),
                payload='empty only', finish='Holder clearance; no seating or release')
    plan['requires_route_review'] = not in_near_home(plan['start'])
    # Validate before creating another receipt; do not silently replace the
    # route the operator reviewed with one based on a different starting pose.
    if args.reviewed_plan:
        validate_review(json.loads(args.reviewed_plan.read_text(encoding='utf-8')), plan)
    REPORTS.mkdir(parents=True, exist_ok=True)
    preview_path = REPORTS/('preview_'+uuid4().hex+'.json')
    write_run_record(preview_path, plan)
    print(json.dumps(dict(motion_started=False, plan=plan, preview=str(preview_path)), indent=2), flush=True)
    if not args.execute:
        return plan
    if plan['requires_route_review'] and not args.reviewed_plan:
        raise RuntimeError('New HOME connector passes IK but needs physical clearance review. Inspect the saved preview, then use --reviewed-plan "'+str(preview_path)+'" --execute --empty-gripper only when the arm is free and the full route is clear. No movement started.')
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS/(uuid4().hex+'.json')
    record = dict(status='starting', started_at=time.time(), plan=plan,
                  before=state, native=native, events=[], automatic_retries=False,
                  reviewed_plan=str(args.reviewed_plan) if args.reviewed_plan else None,
                  authorization='--execute --empty-gripper; clear route and jaw sweep, hands clear, E-stop supervised')
    def save():
        write_run_record(path, record)
    def event(name, result):
        record['events'].append(dict(name=name, result=result, at=time.time()))
        save()
        if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
            raise RuntimeError('Unconfirmed '+name+'; no retry.')
    sent = False
    save()
    try:
        fresh, axes = checked_state()
        near(fresh['robot']['pose_mm'], plan['start'], .05)
        if any(abs(fresh['robot']['joints'][k]-v) > .1 for k,v in state['robot']['joints'].items()):
            raise RuntimeError('Starting joints changed after preview.')
        # The existing generic move command writes E1=0. Explicitly close EMPTY
        # jaws before travel; never use this connector for a held plate.
        if abs(axes['external_axes']['E1']) > .15:
            sent = True
            event('close_empty_jaws', api('gripper', dict(action='move', e1=0, speed=5)))
        previous = plan['start']
        for point in points:
            fresh, axes = checked_state()
            near(fresh['robot']['pose_mm'], previous, .05)
            if abs(axes['external_axes']['E1']) > .15:
                raise RuntimeError('Empty-jaw closure did not verify.')
            if all(abs(previous[k]-point[k]) <= .01 for k in ('X','Y','Z','Rz')):
                continue
            sent = True
            event('move_HOME', api('move', dict(x=point['X'], y=point['Y'], z=point['Z'],
                                               rz=point['Rz'], speed=5, interpolation='linear')))
            fresh, _ = checked_state()
            near(fresh['robot']['pose_mm'], point, .05)
            previous = point
        final, _ = checked_state()
        near(final['robot']['pose_mm'], g['home'], .05)
        record.update(status='completed_empty_HOME_clearance', final=final)
    except BaseException as exc:
        record.update(status='stopped_or_uncertain', error=str(exc))
        if sent:
            try:
                record['stop'] = api('program', {'action':'stop'})
            except Exception as stop_error:
                record['stop_error'] = str(stop_error)
        raise
    finally:
        record['finished_at'] = time.time()
        save()
        print(json.dumps(dict(status=record['status'], record=str(path))), flush=True)
    return record


if __name__ == '__main__':
    main()
