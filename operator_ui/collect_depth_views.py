"""Supervised, bounded XY image collection of the two-circle plate.

Fixed Z/Rz, 2 mm steps, maximum +/-4 mm from the inspected pose. No labels
are inferred from predictions. A first invocation can stop after one pilot
move for visual review. Uncertain or failed runs cannot automatically resume.
An explicitly inspected torque-only pause can resume at a verified, captured
endpoint. XY travel uses the existing GuardedService collision/error/path and
arrival checks. The Z-descent torque band is not a calibrated XY collision
threshold; torque remains recorded, and grip load / unstable telemetry stops.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import time

import cv2
import numpy as np

from robot_service import RobotService
from camera_service import CameraService
from sequences import Runner, get_robot_params, band_floor
from autonomy import GuardedService, check_path, wrap
from depth_scene import DATASET, capture_sample, write_json
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'grab_skill'))
import mcp_teach


OFFSETS = [(0, 0), (2, 0), (2, 2), (0, 2), (-2, 2), (-2, 0),
           (-2, -2), (0, -2), (2, -2), (4, -2), (4, 0), (4, 2),
           (4, 4), (2, 4), (0, 4), (-2, 4), (-4, 4), (-4, 2),
           (-4, 0), (-4, -2), (-4, -4), (-2, -4), (0, -4), (2, -4), (4, -4),
           (2, -4), (0, -4), (0, -2), (0, 0)]


def close_pose(actual, expected, tolerance=.15):
    if any(abs(actual[k] - expected[k]) > tolerance for k in ('X', 'Y', 'Z')):
        raise RuntimeError('Pose differs from the inspected/recorded pose; no automatic retry')
    if abs(wrap(actual['Rz'] - expected['Rz'])) > .05:
        raise RuntimeError('Wrist angle differs from the inspected/recorded pose')


def verify_plate(current, reference, previous=None):
    if not current or not reference:
        raise RuntimeError('Both plate circles must remain detectable; stopped without further motion')
    for name in ('big_r', 'small_r'):
        if not .95 < current[name] / reference[name] < 1.05:
            raise RuntimeError('Plate circle size changed by more than 5%; inspect scene')
    if abs(wrap(current['mark'][2] - reference['mark'][2])) > 2:
        raise RuntimeError('Plate image orientation changed unexpectedly')
    for center, radius in (('big_c', 'big_r'), ('small_c', 'small_r')):
        x, y = current[center]
        r = current[radius]
        if min(x-r, y-r, 3072-x-r, 2048-y-r) < 120:
            raise RuntimeError('Plate-circle visibility margin is too small')
    if previous is not None:
        shift = math.dist(current['mark'][:2], previous['mark'][:2])
        if not 3 < shift < 100:
            raise RuntimeError(f'Unexpected image response to 2 mm move: {shift:.1f} px')


def inspected_resume(ledger, folder, targets, reference):
    if ledger.get('state') != 'error' or ledger.get('error') not in (
            'Unexpected J2 torque change; stopped', 'Unexpected J3 torque change; stopped',
            'Unexpected J4 torque change; stopped'):
        raise RuntimeError('Inspected resume only handles a torque-only pause, never an uncertain move')
    if ledger.get('reference') != str(reference):
        raise RuntimeError('Reference changed')
    index = ledger['next_index']
    if not 0 < index < len(targets):
        raise RuntimeError('No captured endpoint to resume')
    close_pose(ledger['commanded'], targets[index])
    after = ledger['robot_after_error']
    if not after.get('ok') or after.get('errors'):
        raise RuntimeError('Error state did not verify a fault-free arrival')
    close_pose(after['pose_mm'], targets[index])
    matches = []
    for path in folder.glob('*/metadata.json'):
        meta = json.loads(path.read_text())
        if meta.get('collection', {}).get('index') == index:
            close_pose(meta['robot_pose_after_mm'], targets[index])
            close_pose(meta['robot_pose_before_mm'], targets[index])
            matches.append(meta['collection']['circle_detection'])
    if len(matches) != 1:
        raise RuntimeError('Require exactly one saved image at the inspected endpoint')
    return index, targets[index], matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True, help='Inspected sample folder')
    parser.add_argument('--session', required=True)
    parser.add_argument('--execute', action='store_true', help='Human confirmed supervision and clear empty-gripper XY travel')
    parser.add_argument('--moves', type=int, default=1, help='Stop for review after this many moves; max 28')
    parser.add_argument('--resume-after-inspection', action='store_true',
                        help='Operator explicitly inspected the stopped arm and confirmed no contact or cable tension')
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', args.session):
        parser.error('Invalid session name')
    if not 1 <= args.moves <= 28:
        parser.error('moves must be 1..28')
    reference = Path(args.reference).resolve()
    meta = json.loads((reference / 'metadata.json').read_text())
    origin = meta['robot_pose_after_mm']
    ref_detection = mcp_teach.sdk_detect(str(reference / 'rgb.png'))
    verify_plate(ref_detection, ref_detection)
    targets = [{**origin, 'X': origin['X'] + dx, 'Y': origin['Y'] + dy} for dx, dy in OFFSETS]
    if not 250 <= origin['Z'] <= 400:
        raise RuntimeError('This collector requires inspected TCP height 250..400 mm')
    service, camera, runner = RobotService(), CameraService(), Runner()
    params = get_robot_params()
    guard = GuardedService(service, runner, params)
    folder = DATASET / args.session
    ledger_path = folder / 'collection.json'
    ledger = None
    recovered_detection = None
    executing = False
    try:
        GuardedService.checked(service.connect())
        status = service.status()
        if not status.get('ok') or status.get('errors'):
            raise RuntimeError(f'Robot status prevents collection: {status}')
        if not service.envelope_enabled:
            raise RuntimeError('Workspace envelope must remain enabled')
        if ledger_path.exists():
            ledger = json.loads(ledger_path.read_text())
            if args.resume_after_inspection:
                index, expected, recovered_detection = inspected_resume(ledger, folder, targets, reference)
            else:
                if ledger['state'] != 'paused_for_review' or ledger['reference'] != str(reference):
                    raise RuntimeError('Only the reviewed, matching paused run can continue')
                index = ledger['next_index']
                expected = targets[index - 1]
        else:
            index = 0
            expected = origin
        close_pose(status['pose_mm'], expected)
        p, q = status['pose_mm'], status['joints']
        for target in targets[index:]:
            if math.dist([p['X'], p['Y']], [target['X'], target['Y']]) > 2.01:
                raise RuntimeError('Planned step exceeds 2 mm')
            q = check_path(p, target, q, params, service.envelope)
            p = target
        print(json.dumps(dict(plan_checked=True, origin=origin, unique_views=25,
                             return_views=4, remaining=len(targets)-index,
                             step_mm=2, speed=5, execute=args.execute)), flush=True)
        if not args.execute:
            return
        executing = True
        folder.mkdir(parents=True, exist_ok=True)
        if ledger is None:
            ledger = dict(state='preparing', reference=str(reference), origin=origin,
                          targets=targets, next_index=0, samples=[], started_at=time.time(),
                          ground_truth=None, training_status='awaiting_independent_depth_labels')
        if recovered_detection is not None:
            ledger.setdefault('inspection_recoveries', []).append(dict(
                time=time.time(), operator_confirmed_clear=True, pose=status['pose_mm'],
                prior_error=ledger.get('error'), prior_torque=ledger.get('last_torque'),
                prior_baseline=ledger.get('torque_baseline')))
            ledger.pop('error', None)
        ledger['xy_torque_policy'] = ('Record telemetry; existing GuardedService path, arrival and '
                                      'controller-error checks. Z-descent band is not an XY delta threshold.')
        ledger['state'] = 'preparing'
        write_json(ledger_path, ledger)
        if status['control_mode']['mode'] != 'auto':
            GuardedService.checked(service.switch_mode('auto'))
        if not service.robot.get_enable_status():
            GuardedService.checked(service.set_enable(True, confirmed=True))
        if service.robot.get_prog_state()['state'] != 'running':
            print('Starting the paused program through stop/start; empty gripper was confirmed.', flush=True)
            GuardedService.checked(service.program('start'))
        close_pose(service.pose_mm(), expected)
        torque_band = band_floor()
        readings = []
        for _ in range(5):
            readings.append(guard.torque_report())
            time.sleep(.3)
        if min(r['e1_torque'] for r in readings) <= -100:
            raise RuntimeError('Gripper torque indicates a possible held object')
        initial_torque = {joint: float(np.median([r['joints'][joint] for r in readings]))
                          for joint in ('J1', 'J2', 'J3', 'J4')}
        for joint in ('J2', 'J3', 'J4'):
            if np.ptp([r['joints'][joint] for r in readings]) > torque_band:
                raise RuntimeError('Stationary torque unstable; stopped before motion')
        ledger['torque_baseline'] = dict(median=initial_torque, band=torque_band, samples=readings)
        write_json(ledger_path, ledger)
        previous = recovered_detection or (ledger['samples'][-1]['detection'] if ledger['samples'] else ref_detection)
        moves = 0
        # Recheck the current scene before the first move on every invocation.
        initial_frame = camera.snap()
        stationary_path = camera.save(initial_frame, prefix=f'depth_check_{time.time_ns()}')
        stationary = mcp_teach.sdk_detect(stationary_path)
        verify_plate(stationary, ref_detection)
        if math.dist(stationary['mark'][:2], previous['mark'][:2]) > 8:
            raise RuntimeError('Scene changed while stationary; inspect plate before proceeding')
        while index < len(targets):
            if (folder / 'STOP').exists():
                raise RuntimeError('Operator STOP file found')
            target = targets[index]
            before = guard.pose_mm()
            close_pose(before, expected)
            moved = math.dist([before['X'], before['Y']], [target['X'], target['Y']]) > .15
            if moved:
                ledger.update(state='moving', commanded=target)
                write_json(ledger_path, ledger)
                guard.move_cartesian(target['X'], target['Y'], origin['Z'], origin['Rz'], 5)
                moves += 1
            time.sleep(.25)
            pose_before = guard.pose_mm()
            close_pose(pose_before, target)
            frame = camera.snap()
            pose_after = guard.pose_mm()
            close_pose(pose_after, pose_before, .05)
            sample, metadata = capture_sample(frame, args.session, pose_before, pose_after, camera.info())
            detection = mcp_teach.sdk_detect(str(sample / 'rgb.png'))
            h, w = frame.shape[:2]
            cv2.imwrite(str(sample / 'preview.jpg'), cv2.resize(frame, (1400, round(h * 1400/w))))
            metadata['collection'] = dict(index=index, offset_mm=OFFSETS[index],
                                          role='unique_view' if index < 25 else 'return_repeat',
                                          labels_available=False, circle_detection=detection)
            write_json(sample / 'metadata.json', metadata)
            verify_plate(detection, ref_detection, previous if moved else None)
            torques = guard.torque_report()
            ledger['last_torque'] = torques
            if torques['e1_torque'] <= -100:
                raise RuntimeError('Unexpected gripper load; stopped')
            record = dict(index=index, sample=str(sample), pose=pose_after,
                          detection=detection, torque=torques['joints'])
            ledger['samples'].append(record)
            index += 1
            ledger.update(state='paused_for_review', next_index=index, last_pose=pose_after)
            write_json(ledger_path, ledger)
            print(json.dumps(dict(captured=index, total=len(targets), sample=str(sample),
                                  pose=pose_after, circles=detection)), flush=True)
            previous, expected = detection, target
            if moves >= args.moves:
                break
        if index == len(targets):
            close_pose(guard.pose_mm(), origin)
            ledger.update(state='complete', completed_at=time.time())
        write_json(ledger_path, ledger)
        print(json.dumps(dict(state=ledger['state'], images=len(ledger['samples']),
                              final_pose=service.pose_mm(), robot_motion_complete=index == len(targets),
                              training='not started; requires independent depth labels')), flush=True)
    except BaseException as error:
        if ledger is not None and executing:
            ledger.update(state='error', error=str(error))
            try:
                ledger['robot_after_error'] = service.status()
                write_json(ledger_path, ledger)
            except Exception:
                pass
        raise
    finally:
        camera.release()
        service.disconnect()


if __name__ == '__main__':
    main()
