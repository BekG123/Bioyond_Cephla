"""One operator-authorized replacement, regrip and repeat of an accepted lift."""
import hashlib
import json
import math
import time

from autonomy import TransferError, check_path
from loaded_home_trial import near
from scope_compact137 import HoldingService
from staged_lift_trial import OUTPUT as PARENT
from trajectory_queue import LuaTrajectory, prepare_points

ACCEPTANCE = PARENT.with_name('e1_3p7_20261020_lift_acceptance.json')
OUTPUT = PARENT.with_name('e1_3p7_20261020_replace_regrip_lift.json')
PREVIOUS_7 = OUTPUT
ACCEPTANCE_7 = PARENT.with_name('e1_3p7_20261020_replace_regrip_acceptance.json')
OUTPUT_7 = PARENT.with_name('e1_3p7_20261020_open7_regrip_lift.json')


def review(service,cfg,opening_mm=5.0):
    if type(opening_mm) not in (int,float) or opening_mm not in (5.0,7.0):
        raise TransferError('Only the specifically authorized 5 or 7 mm opening trials are supported.')
    output = OUTPUT_7 if opening_mm == 7 else OUTPUT
    acceptance = ACCEPTANCE_7 if opening_mm == 7 else ACCEPTANCE
    if output.exists():
        raise TransferError('This regrip trial was already attempted; review before repeating.')
    raw, accepted_raw = PARENT.read_bytes(), acceptance.read_bytes()
    parent, accepted = json.loads(raw), json.loads(accepted_raw)
    previous_raw = PREVIOUS_7.read_bytes() if opening_mm == 7 else raw
    previous = json.loads(previous_raw)
    if (parent['status'] != 'completed_awaiting_plate_retention_feedback'
            or previous['status'] != 'completed_awaiting_plate_retention_feedback'
            or accepted.get('source') != (PREVIOUS_7.name if opening_mm == 7 else PARENT.name)
            or accepted.get('plate_stayed_level_without_slipping') is not True):
        raise TransferError('Accepted lift evidence required.')
    state = service.status()
    if (not state.get('ok') or not state.get('connected') or state.get('errors')
            or not state.get('enabled') or state['control_mode']['mode'] != 'auto'
            or state['program_state']['state'] != 'running'):
        raise TransferError('Healthy running Auto required; no startup or reset.')
    previous_plan = parent['plan']
    if cfg != previous_plan['cfg'] or {k:list(v) for k,v in service.envelope.items()} != previous_plan['envelope']:
        raise TransferError('Kinematics or workspace changed.')
    start = previous_plan['stages'][-1]['target']
    near(state['pose_mm'],start)
    guarded = HoldingService(service,3.7,previous_plan['envelope'])
    refusal = guarded._preflight()
    if refusal:
        raise TransferError(refusal)
    if abs(service.external_axes()['E1']-3.7) > .05:
        raise TransferError('Held opening changed.')
    support = LuaTrajectory(guarded).capability()
    if not support.get('available') or support.get('max_speed_mm_s',0) < 137:
        raise TransferError('Running speed-137 Lua queue required.')
    holder = {**start,'Z':previous_plan['start']['Z']}
    legs = [dict(label='Return to holder',target=holder,speed=5),
            dict(label='Slow lift',target=previous_plan['stages'][0]['target'],speed=5),
            dict(label='Fast lift',target=start,speed=137)]
    previous,joints = start,state['joints']
    for leg in legs:
        points,expected = prepare_points(previous,joints,[leg['target']],cfg,
                                         reviewed=True,home_transit=True)
        check_path(previous,points[0],joints,cfg,service.envelope)
        leg['target'] = points[0]
        previous,joints = points[0],expected
    if abs(legs[0]['target']['Z']-start['Z']+30) > .01:
        raise TransferError('Only the accepted 30 mm vertical return is allowed.')
    return dict(parent_sha256=hashlib.sha256(raw).hexdigest(),
                previous_attempt_sha256=hashlib.sha256(previous_raw).hexdigest(),
                acceptance_sha256=hashlib.sha256(accepted_raw).hexdigest(),
                start=start,legs=legs,cfg=cfg,envelope=previous_plan['envelope'],
                open_e1_mm=opening_mm,close_e1_mm=3.7,grip_speed=5,
                closing_targets=([6.0,5.0] if opening_mm == 7 else [])+
                                [4.8,4.6,4.4,4.2,4.0,3.9,3.8,3.7])


def execute(run,service,cfg,approved):
    opening = approved['open_e1_mm']
    output = OUTPUT_7 if opening == 7 else OUTPUT
    if review(service,cfg,opening) != approved:
        raise TransferError('Trial changed before dispatch.')
    record = dict(status='started',at=time.time(),plan=approved,stages=[],samples=[],
                  grasp_verified=False,force_limits_changed=False)
    with output.open('x',encoding='utf-8') as stream:
        json.dump(record,stream,indent=2)
    def save():
        output.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    guarded = HoldingService(service,3.7,approved['envelope'])
    def check(expected_pose=None):
        if run.stopped():
            raise TransferError('Trial stopped; no next command.')
        refusal = service._preflight()
        if refusal:
            raise TransferError(refusal)
        if not service.envelope_enabled or {k:list(v) for k,v in service.envelope.items()} != approved['envelope']:
            raise TransferError('Workspace changed.')
        if expected_pose:
            near(service.pose_mm(),expected_pose)
    def travel(leg):
        check()
        item=dict(kind='arm',**leg,at=time.time())
        record['stages'].append(item);save()
        def progress(phase,done,total):
            record['samples'].append(dict(at=time.time(),label=leg['label'],phase=phase,
                progress=done,pose_mm=service.pose_mm(),e1_mm=service.external_axes()['E1']))
            run.say(f'{leg["label"]}: {phase} {done:.0f}/{total}.')
        item['result']=LuaTrajectory(guarded).execute(
            run,service.pose_mm(),service.joints(),[leg['target']],cfg,leg['speed'],progress,
            reviewed=True,home_transit=True,home_speed137=True)
        item['finished_at']=time.time();save()
        if item['result'].get('ok') is not True:
            raise TransferError('Arm motion uncertain; no next action.')
        near(service.pose_mm(),leg['target'],.05)
    holder=approved['legs'][0]['target']
    def jaw(target,expected):
        check(holder)
        if abs(service.external_axes()['E1']-expected) > .05:
            raise TransferError('Jaw opening changed before command.')
        item=dict(kind='gripper',target_e1_mm=target,speed=5,at=time.time())
        record['stages'].append(item);save()
        response=service.move_gripper(target,speed=5)
        item['response']=response;save()
        if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
            raise TransferError('Jaw command uncertain; no retry or lift.')
        deadline=time.monotonic()+2;stable=0
        while stable<3:
            check(holder)
            value=service.external_axes()['E1']
            if not math.isfinite(value) or time.monotonic()>deadline:
                raise TransferError('Jaw did not settle; no next action.')
            stable=stable+1 if abs(value-target)<=.02 else 0
            if stable<3:time.sleep(.1)
        report=service.torque_report()
        item.update(settled_e1_mm=value,torque_report=report,finished_at=time.time());save()
        if (report.get('ok') is not True or report.get('telemetry_live') is not True
                or report.get('recovered') or abs(report['e1_position']-target)>.05
                or not math.isfinite(report['e1_torque'])):
            raise TransferError('Fresh gripper telemetry unavailable; no next action.')
        check(holder)
        run.say(f'Claw at {value:.3f} mm.')
    try:
        travel(approved['legs'][0])
        jaw(opening,3.7)
        expected=opening
        for target in approved['closing_targets']:
            jaw(target,expected)
            expected=target
        end=time.monotonic()+2
        while time.monotonic()<end:
            check(holder)
            refusal=guarded._preflight()
            if refusal:raise TransferError(refusal)
            time.sleep(.1)
        for leg in approved['legs'][1:]:
            travel(leg)
        record.update(status='completed_awaiting_plate_retention_feedback',
                      finished_at=time.time(),final=service.status())
        return dict(ok=True,record=str(output),pose_mm=service.pose_mm(),grasp_verified=False)
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error),finished_at=time.time())
        record['stop_response']=service.program('stop')
        raise
    finally:
        save()
        run.audit('replace_regrip_two_speed_lift',record=record)
