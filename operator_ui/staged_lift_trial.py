"""One fixed 5 mm @ 5, then 25 mm @ 137 pickup trial via the Flask owner."""
import hashlib
import json
from pathlib import Path
import time

from autonomy import TransferError, check_path
from loaded_home_trial import near
from scope_compact137 import HoldingService
from trajectory_queue import LuaTrajectory, prepare_points

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'operator_ui/demonstrations/reference_grip/917f9536b09c4f04b24b748c59187e97.json'
OUTPUT = SOURCE.with_name('e1_3p7_20261020_two_speed_lift.json')


def review(service, cfg):
    if OUTPUT.exists():
        raise TransferError('This lift has already been attempted; review its result.')
    raw = SOURCE.read_bytes()
    grip = json.loads(raw)
    if grip.get('ok') is not True or grip.get('target_e1_mm') != 3.7:
        raise TransferError('Completed 3.7 mm closure required.')
    state = service.status()
    if (not state.get('ok') or not state.get('connected') or state.get('errors')
            or not state.get('enabled') or state['control_mode']['mode'] != 'auto'
            or state['program_state']['state'] != 'running'):
        raise TransferError('Healthy, already-running Auto required; no startup or reset.')
    start = {k:grip['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    near(state['pose_mm'], start)
    envelope = {k:list(v) for k,v in service.envelope.items()}
    guarded = HoldingService(service, 3.7, envelope)
    refusal = guarded._preflight()
    if refusal:
        raise TransferError(refusal)
    if abs(service.external_axes()['E1']-3.7) > .05:
        raise TransferError('Grip setting changed.')
    capability = LuaTrajectory(guarded).capability()
    if not capability.get('available') or capability.get('max_speed_mm_s',0) < 137:
        raise TransferError('Published speed-137 queue required; no automatic restart.')
    stages = [dict(target={**start,'Z':start['Z']+5},speed=5),
              dict(target={**start,'Z':start['Z']+30},speed=137)]
    previous, joints = start, state['joints']
    for stage in stages:
        points, expected = prepare_points(previous, joints, [stage['target']], cfg,
                                          reviewed=True, home_transit=True)
        check_path(previous, points[0], joints, cfg, service.envelope)
        stage['target'] = points[0]
        previous, joints = points[0], expected
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(), start=start,
                stages=stages, cfg=cfg, envelope=envelope, target_e1_mm=3.7,
                transition='Two consecutive queue batches; endpoint stop and upload between speeds.')


def execute(run, service, cfg, approved):
    current = review(service, cfg)
    if current != approved:
        raise TransferError('Lift review changed before dispatch.')
    record = dict(status='started', at=time.time(), plan=approved, stages=[], samples=[],
                  grasp_verified=False, gripper_commands=False,
                  operator_instruction='Try a continous motion: lift 5 mm up at 5 speed adn then 137 speed up like 25 mm')
    with OUTPUT.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2)
    def save():
        OUTPUT.write_text(json.dumps(record,indent=2,allow_nan=False), encoding='utf-8')
    guarded = HoldingService(service, 3.7, approved['envelope'])
    try:
        for index, stage in enumerate(approved['stages'], 1):
            if run.stopped():
                raise TransferError('Stopped before next lift stage.')
            item = dict(index=index, target=stage['target'], speed=stage['speed'], at=time.time())
            record['stages'].append(item)
            save()
            def progress(phase, done, total):
                record['samples'].append(dict(at=time.time(),stage=index,phase=phase,
                    progress=done,pose_mm=service.pose_mm(),e1_mm=service.external_axes()['E1']))
                run.say(f'Lift {index}/2: {phase} {done:.0f}/{total} at speed {stage["speed"]}.')
            result = LuaTrajectory(guarded).execute(
                run,service.pose_mm(),service.joints(),[stage['target']],cfg,stage['speed'],progress,
                reviewed=True,home_transit=True,home_speed137=True)
            item.update(result=result,finished_at=time.time())
            save()
            if result.get('ok') is not True:
                raise TransferError('Lift stage uncertain; no next stage.')
            near(service.pose_mm(), stage['target'], .1)
        record.update(status='completed_awaiting_plate_retention_feedback',
                      final=service.status(),finished_at=time.time())
        return dict(ok=True,record=str(OUTPUT),pose_mm=service.pose_mm(),grasp_verified=False)
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error),finished_at=time.time())
        record['stop_response'] = service.program('stop')
        raise
    finally:
        save()
        run.audit('two_speed_pickup_lift',record=record)
