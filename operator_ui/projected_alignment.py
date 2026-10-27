"""48-well alignment commissioning. No descent, grip or reusable grasp target.

Uses the vendor Wide XY/yaw transform and taught camera-to-claw transform.
Virtual disk radii never enter the depth solver. Observation height comes
only from the physically verified, same-support height-transfer reference.
"""
import hashlib
import json
import time
import uuid

import cv2
import numpy as np
import teach
from projected_disk_trial import ROOT, Perception, same_pose, stationary_observation
from grid_pattern import HeightReferencedGridPattern
from autonomy import GuardedService, TransferError, alignment_plan, number, wrap

REFERENCE = ROOT/'Pick and Hold/Calibration/plate_48_height_reference_20261026.json'


def pinned_json(path, digest):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise TransferError('Height-reference evidence changed.')
    return json.loads(raw)


def perception_at_height():
    reference = json.loads(REFERENCE.read_text())
    if not reference.get('live_arrival_and_relative_scale_verified') or not reference.get('same_bottom_support_confirmed'):
        raise TransferError('Verified same-support observation height required.')
    evidence = pinned_json(ROOT/reference['evidence'], reference['evidence_sha256'])
    log = ROOT/evidence['final_log']
    raw = log.read_bytes()
    if hashlib.sha256(raw).hexdigest() != evidence['final_log_sha256']:
        raise TransferError('Height stationary log changed.')
    events = [json.loads(line) for line in raw.decode().splitlines()]
    if not events[-1]['result'].get('ok'):
        raise TransferError('Height stationary trial did not complete.')
    frames = [e for e in events if e['event'] == 'stationary_image_burst']
    if len(frames) != 6:
        raise TransferError('Six accepted final height images required.')
    p = Perception('anchored_grid', 5, True)
    accepted = []
    for entry in frames:
        frame = cv2.imread(entry['median_image'])
        accepted.append(p.measure(frame, entry['pose']))
    corners = [np.asarray(m['tracking']['corners_px']) for m in accepted]
    if max(np.linalg.norm(a-b, axis=1).max() for a in corners for b in corners) > .8:
        raise TransferError('Saved height observations disagree.')
    # Fixed final image, never selected by how well it matches the new scene.
    p.tracker.previous_verified_seed = None
    p.tracker = HeightReferencedGridPattern(p.tracker, frame)
    p.last_measurement_pose = None
    return p, reference, dict(image=frames[-1]['median_image'],
        image_sha256=hashlib.sha256(frame.tobytes()).hexdigest(),
        reference_sha256=hashlib.sha256(REFERENCE.read_bytes()).hexdigest())


def target_from_mark(pose, measurement, cfg):
    current = teach.mark_in_robot_pose(cfg, measurement['mark'])
    camera = teach.new_acc_pose([pose['X'], pose['Y'], pose['Z'], 0, 0, pose['Rz']],
                               teach.tool_offset_xyrz(cfg, current))
    tool = teach.final_acc_pose(cfg, camera)
    if not np.isfinite(tool).all():
        raise TransferError('Nonfinite projected alignment target.')
    # Z is deliberately absent: this is a lateral/yaw alignment reference only.
    return dict(x=float(tool[0]), y=float(tool[1]), rz=float(wrap(tool[5])))


def plan(pose, measurement, cfg, joints, params, envelope):
    target = target_from_mark(pose, measurement, cfg)
    if np.hypot(target['x']-pose['X'], target['y']-pose['Y']) > 150:
        raise TransferError('Alignment translation exceeds the local plate work area.')
    hover = max(300., pose['Z'])
    # Shared planner requires a lower Z for its clearance arithmetic. This
    # placeholder never becomes an executed or published descent coordinate.
    placeholder = dict(target, z_calibrated=hover-20)
    legs = alignment_plan(pose, placeholder, joints, params, envelope,
                          hover_z=hover, validate_descent=False)
    return dict(target=target, hover_z=hover, waypoints=legs,
        translation_speed=5, wrist_speed=30, descent_authorized=False,
        grasp_target_created=False)


def validate_request(body):
    if not isinstance(body, dict) or any(body.get(k) is not True for k in ('confirm','cell_clear','empty_gripper')):
        raise TransferError('Confirm supervised alignment with empty jaws and clear alignment sweep.')
    pose = {k:number(body.get('expected_start',{}).get(k), k) for k in ('X','Y','Z','Rz')}
    target = {k:number(body.get('expected_target',{}).get(k), k) for k in ('x','y','rz')}
    return dict(expected_start=pose, expected_target=target)


def align(run, svc, cam, params, config):
    from sequences import seq_align
    run.target = None
    guard = GuardedService(svc, run, params)
    folder = ROOT/'operator_ui/reports/projected_alignment'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.jsonl')
    def record(event, **fields):
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(timestamp=time.time(), event=event, **fields))+'\n')
    try:
        guard._preflight()
        start = guard.pose_mm()
        if not same_pose(start, config['expected_start']):
            raise TransferError('Alignment start changed; prepare a fresh route.')
        p, reference, provenance = perception_at_height()
        if abs(start['Z']-reference['observation_z_mm']) > .1:
            raise TransferError('Return to verified observation height before measuring alignment.')
        measurements = []
        for _ in range(2):
            pose, measurement = stationary_observation(guard, cam, p, record)
            measurements.append(measurement)
        targets = [target_from_mark(start,m,p.cfg) for m in measurements]
        if (np.hypot(targets[0]['x']-targets[1]['x'],targets[0]['y']-targets[1]['y']) > .5
                or abs(wrap(targets[0]['rz']-targets[1]['rz'])) > .2):
            raise TransferError('Stationary alignment targets disagree.')
        route = plan(start,measurement,p.cfg,svc.joints() or {},params,svc.envelope)
        expected = config['expected_target']; target = route['target']
        if (np.hypot(target['x']-expected['x'],target['y']-expected['y']) > .5
                or abs(wrap(target['rz']-expected['rz'])) > .2):
            raise TransferError('Plate target changed from the reviewed alignment route.')
        telemetry = guard.torque_report()
        e1 = number(telemetry.get('e1_position'),'claw position')
        if number(telemetry.get('e1_torque'),'claw torque') <= -100:
            raise TransferError('Gripper may be loaded; empty jaws required.')
        if not same_pose(start,guard.pose_mm()):
            raise TransferError('Arm moved before alignment.')
        record('alignment_plan',start=start,route=route,reference=provenance)
        run.say('Aligning above the 48-well plate; descent and grip remain idle.')
        result = seq_align(run,svc,dict(target,z_calibrated=route['hover_z']-20),
                           route['hover_z'],validate_descent=False)
        if not result.get('ok'):
            raise TransferError(result.get('error','Alignment did not complete.'))
        if abs(number(guard.torque_report().get('e1_position'),'claw position')-e1) > .1:
            raise TransferError('Claw position changed during alignment.')
        result.update(alignment_pose_reached=True,visual_acceptance_pending=True,
            full_calibration_complete=False,descent_executed=False,grip_executed=False,
            grasp_target_created=False,route=route,log_file=str(path))
        record('completed',result=result)
        return result
    except Exception as error:
        result=dict(ok=False,error=str(error),log_file=str(path),grasp_target_created=False)
        record('stopped',result=result)
        run.state='stopped' if run.stopped() else 'error'
        run.say(str(error),'err')
        return result
