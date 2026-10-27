"""Shared station jaw/lift sequence: accepted Squid and supervised Hamilton."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

from autonomy import check_path, TransferError
from researcher_teaching import TeachingError
from scope_compact137 import HoldingService
from scope_step_trial import near
from trajectory_queue import LuaTrajectory, prepare_points, travel_program_blocker

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'demonstrations/reference_grip'
ACTIONS = {'squid_dropoff': 'release', 'squid_retrieve': 'pickup',
           'hamilton_dropoff': 'release', 'hamilton_retrieve': 'pickup'}
SEATED = dict(X=226.3, Y=373.59, Z=266.19, Rz=89.11)
LIFTED = {**SEATED, 'Z': 271.19}


def evidence():
    """Only the two accepted station trials commission these fixed settings."""
    hashes = {}
    for name, status, flag in (
        ('home_squid_dropoff_home_20261020.json', 'operator_accepted_dropoff_and_empty_return',
         'plate_left_flat_at_squid_operator_confirmed'),
        ('squid_post_imaging_retrieval_20261020.json', 'operator_accepted_successful_retrieval',
         'plate_retained_operator_confirmed'),
    ):
        try:
            raw = (EVIDENCE / name).read_bytes()
            data = json.loads(raw.decode('utf-8-sig'))
        except (OSError, ValueError) as error:
            raise TeachingError('The accepted Squid trial record is unavailable. Ask your developer to check it.') from error
        if data.get('status') != status or data.get(flag) is not True or data.get('travel_speed') != 137:
            raise TeachingError('The accepted Squid handling reference needs developer review.')
        if 'release' in data:
            part = data['release']
            near(part['target_pose'], SEATED, .001)
            if (part['e1_target_mm'], part['speed'], data['retreat']['lift_mm'],
                    data['retreat']['speed']) != (5, 5, 5, 5):
                raise TeachingError('Squid release reference changed.')
        else:
            near(data['seated_pose'], SEATED, .001)
            if (data['approach_e1_mm'], data['closing']['target_e1_mm'],
                    data['closing']['speed'], data['lift']['delta_mm'],
                    data['lift']['speed']) != (5, 3.7, 5, 5, 5):
                raise TeachingError('Squid pickup reference changed.')
        hashes[name] = hashlib.sha256(raw).hexdigest()
    return hashes


def context(action):
    if action not in ACTIONS:
        raise TeachingError('Unknown station handling operation.')
    if action.startswith('hamilton_'):
        from hamilton_handling import reference
        seated,lifted,hashes=reference()
        return 'Hamilton',seated,lifted,hashes
    return 'Squid',SEATED,LIFTED,evidence()


def lift_check(station,start,target,joints,cfg,envelope):
    if station=='Hamilton':
        from hamilton_handling import check_lift
        return check_lift(start,target,joints,cfg)
    q=check_path(start,target,joints,cfg,envelope)
    q['J1']=joints['J1']+target['Z']-start['Z']
    return q


def plan(backend, action):
    station,seated,lifted,hashes=context(action)
    prefix=station.lower()
    dropoff=ACTIONS[action]=='release'
    state = backend.healthy()  # No automatic preparation: it can close loaded jaws.
    if backend.run.active or (getattr(backend.run, 'reserved', False)
                              and not getattr(backend.run, 'owns_reservation', False)):
        raise TeachingError('Wait for the current task to finish.')
    origin = backend.station(state['pose_mm'], state['joints'])
    seated_start = station == 'Squid' and origin == 'Squid'
    if seated_start:
        try:
            near(state['pose_mm'], seated, .02)
        except TransferError:
            raise TeachingError('The arm is near Squid but not at its taught seated loading position. '
                                'Have the position checked before opening or closing the jaws.') from None
    elif origin != 'Home':
        raise TeachingError(f'Return Home before starting {station} drop-off or retrieval.')
    opening = 3.7 if dropoff else 5.
    after = 5. if dropoff else 3.7
    actual = state.get('external_axes', {}).get('E1')
    if type(actual) not in (float, int) or not math.isfinite(actual) or abs(actual-opening) > .05:
        raise TeachingError(f'This routine requires the jaws at {opening:g} mm at {origin}. '
                            'Ask your developer to check the gripper before retrying.')
    cap = LuaTrajectory(backend.s).capability()
    blocker=travel_program_blocker(cap)
    if blocker:
        raise TeachingError(blocker)
    if seated_start:
        steps, pose, q = [], deepcopy(state['pose_mm']), deepcopy(state['joints'])
    else:
        steps, pose, q = backend.plan_travel('move_hamilton' if station=='Hamilton' else 'move_scope',
                                           state['pose_mm'], state['joints'])
    near(pose, seated, .02)
    for step in steps:
        step['expected_e1'] = opening
    if station=='Hamilton':
        steps.append(dict(kind='hamilton_inspect',label='Check the plate at Hamilton',
                          start=deepcopy(pose),joints=deepcopy(q),expected_e1=opening,
                          review_label=('Confirm the plate rests flat and fully supported at Hamilton, with the jaws clear to open.'
                                        if dropoff else 'Confirm both jaws surround the flat, supported plate at the correct gripping height.')))
    steps.append(dict(kind=prefix+'_jaw', label=(f'Leave the plate at {station}' if after == 5 else
                                             f'Grip the plate at {station}'),
                      start=deepcopy(pose), joints=deepcopy(q), expected_e1=opening,
                      target_e1=after, speed=5))
    points, _ = prepare_points(pose, q, [lifted], backend.params(), reviewed=True)
    end_q = lift_check(station,pose,points[0],q,backend.params(),backend.s.envelope)
    steps.append(dict(kind=prefix+'_lift', label=('Lift the empty jaws clear' if after == 5 else
                                              'Lift the plate slowly'),
                      start=deepcopy(pose), joints=deepcopy(q), expected_e1=after,
                      points=points, speed=5))
    if station=='Hamilton':
        steps.append(dict(kind='hamilton_inspect',label='Check the Hamilton lift',
                          start=deepcopy(points[0]),joints=deepcopy(end_q),expected_e1=after,
                          review_label=('Confirm the plate remains flat in Hamilton and the empty jaws are clear for the return Home.'
                                        if dropoff else 'Confirm the plate lifted evenly and stays secure without slipping before returning Home.')))
    returning, _, _ = backend.plan_travel('move_home', points[0], end_q)
    for step in returning:
        step['expected_e1'] = after
    steps.extend(returning)
    return dict(dispatch=prefix+'_handling', executable=True, prepare=False, actions=[action],
                steps=steps, start=state['pose_mm'], joints=state['joints'], e1=actual,
                cfg=backend.params(), envelope={k:list(v) for k,v in backend.s.envelope.items()},
                handling_evidence=hashes, camera_required=False,
                start_station=origin, seated_start=seated_start,
                summary=(f'Leave the plate at {station}, then return Home empty.' if dropoff else
                         f'Retrieve the plate from {station} and bring it Home.'),
                supervised_trial=station=='Hamilton',
                requirements=[
                    ('The plate is flat and fully supported in the Squid holder; the jaws are clear to open.'
                     if dropoff and seated_start else
                     f'The plate is securely held; the {station} holder is empty and ready to support it.'
                     if dropoff else
                     f'The gripper is empty; the plate is flat in the taught {station} holder, and you authorize retrieval now.'),
                    f'The {station} holder remains in its taught loading position; jaw clearance, 5 mm lift headroom and loaded return are clear.',
                    'Hands are clear, the arm is released, and the emergency stop is supervised.',
                    ('The instrument is not started by this routine.' if dropoff else
                     'Instrument completion is not connected. Confirm only after it is finished, or for an explicit simulated-completion test.'),
                    ('Hamilton local handling is a supervised trial: inspect arrival before jaw motion and inspect the lift before returning Home.'
                     if station=='Hamilton' else 'Use the accepted Squid loading pose.')
                ])


def verify(backend, proposed):
    current = plan(backend, proposed['actions'][0])
    # Existing generic confirmation also verifies live pose, joints and E1.
    for key in ('cfg', 'envelope', 'handling_evidence', 'dispatch', 'prepare', 'executable',
                'start_station', 'seated_start'):
        if current[key] != proposed.get(key):
            raise TeachingError('Station handling settings changed. Request a fresh plan.')
    if len(current['steps']) != len(proposed['steps']):
        raise TeachingError('Station handling steps changed.')
    for expected, actual in zip(current['steps'], proposed['steps']):
        for key in ('kind', 'points', 'profile', 'sources', 'expected_e1', 'target_e1', 'speed','review_label'):
            if expected.get(key) != actual.get(key):
                raise TeachingError('Station handling steps changed.')
        near(actual['start'], expected['start'], .2)
        if any(abs(actual['joints'][k]-expected['joints'][k]) > .5 for k in ('J1','J2','J3','J4')):
            raise TeachingError('Station handling joint configuration changed.')


def execute_local(backend, run, step, proposed):
    service = backend.s
    station,seated,lifted,_=context(proposed['actions'][0])
    def check(e1, pose):
        if run.stopped():
            raise TeachingError(f'Stopped; no next {station} action.')
        backend.healthy()
        if backend.params() != proposed['cfg'] or {
                k:list(v) for k,v in service.envelope.items()} != proposed['envelope']:
            raise TeachingError(f'{station} settings changed.')
        if context(proposed['actions'][0])[3] != proposed['handling_evidence']:
            raise TeachingError(f'{station} handling evidence changed.')
        refusal = HoldingService(service, e1, proposed['envelope'])._preflight()
        if refusal:
            raise TeachingError(refusal)
        near(service.pose_mm(), pose, .05)

    check(step['expected_e1'], step['start'])
    if any(abs(service.joints()[k]-step['joints'][k]) > .5 for k in ('J1','J2','J3','J4')):
        raise TeachingError(f'{station} starting configuration changed.')
    if step['kind']=='hamilton_inspect':
        return dict(ok=True,review_required=True,review_kind='station_handling',review_label=step['review_label'])
    if step['kind'] in ('squid_lift','hamilton_lift'):
        near(step['start'], seated, .05)
        if step['points'] != [lifted] or step['speed'] != 5:
            raise TeachingError('Only the configured 5 mm slow station lift is allowed.')
        lift_check(station,service.pose_mm(),lifted,service.joints(),backend.params(),service.envelope)
        result = LuaTrajectory(HoldingService(service, step['expected_e1'], proposed['envelope'])).execute(
            run, service.pose_mm(), service.joints(), [lifted], backend.params(), 5,
            lambda stage,done,total:run.audit(station.lower()+'_lift_progress',stage=stage,done=done,
                pose=service.pose_mm(),e1=service.external_axes()), reviewed=True)
        if result.get('ok') is not True:
            raise TeachingError(f'{station} lift did not confirm completion.')
        check(step['expected_e1'], lifted)
        return dict(ok=True, result=result, pose_mm=service.pose_mm())
    near(step['start'], seated, .05)
    target = 5. if ACTIONS[proposed['actions'][0]]=='release' else 3.7
    if step['target_e1'] != target or step['speed'] != 5:
        raise TeachingError(f'{station} jaw settings differ from the proposed routine.')
    result = service.move_gripper(target, speed=5)
    run.audit(station.lower()+'_jaw_response',target_e1=target,result=result)
    if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
        raise TeachingError('Jaw movement uncertain. No retry or lift.')
    deadline = time.monotonic()+3
    stable = 0
    while stable < 3:
        check(target, seated)
        value = service.external_axes().get('E1')
        if type(value) not in (int,float) or not math.isfinite(value) or time.monotonic() > deadline:
            raise TeachingError('Jaw position did not settle. No next action.')
        stable = stable+1 if abs(value-target) <= .02 else 0
        if stable < 3:
            time.sleep(.1)
    report = service.torque_report()
    run.audit(station.lower()+'_jaw_settled',report=report)
    if (not report.get('ok') or report.get('telemetry_live') is not True or report.get('recovered')
            or not math.isfinite(report.get('e1_position', float('nan')))
            or abs(report.get('e1_position', float('inf'))-target) > .05
            or not math.isfinite(report.get('e1_torque', float('nan')))):
        raise TeachingError('Fresh jaw telemetry unavailable. No next action.')
    check(target, seated)
    return dict(ok=True, gripper=result, settled_report=report, grasp_verified=False)
