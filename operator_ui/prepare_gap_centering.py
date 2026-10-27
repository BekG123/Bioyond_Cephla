"""Prepare, never execute, a measured-gap descent candidate from fresh vision."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from autonomy import TransferError, wrap
from pick_and_hold.Calibration.fast_disk import load_configs, sdk_detect, trans_img_pos_2_world
from prepare_adapted_descent import ROOT, get, prepare

FEEDBACK = ROOT/'operator_ui/demonstrations/supervised_grip/fce738dcaeb24a4ebee238795f4cc539_operator_feedback.json'
PREVIOUS = ROOT/'operator_ui/reports/descent_trials/adapted_20261020T050727394171Z/review.json'


def centering_delta(big_tool, small_tool, camera_rz, left_range, right_range):
    """Base +Z points up; viewed from above, left of big->small is (dy,-dx)."""
    values = [*big_tool, *small_tool, camera_rz, *left_range, *right_range]
    if not all(math.isfinite(float(v)) for v in values):
        raise TransferError('Nonfinite centering measurement.')
    if not (0 <= left_range[0] <= left_range[1] < right_range[0] <= right_range[1]):
        raise TransferError('Require disjoint, positive gap ranges with right gap larger.')
    shift_range = [(right_range[0]-left_range[1])/2, (right_range[1]-left_range[0])/2]
    if shift_range[1] > 1:
        raise TransferError('Gap correction exceeds this reviewed 1 mm experiment.')
    dx, dy = small_tool[0]-big_tool[0], small_tool[1]-big_tool[1]
    length = math.hypot(dx,dy)
    if length < 1:
        raise TransferError('Disk direction is degenerate.')
    a = math.radians(camera_rz)
    bx, by = (math.cos(a)*dx-math.sin(a)*dy)/length, (math.sin(a)*dx+math.cos(a)*dy)/length
    distance = sum(shift_range)/2
    return dict(X=distance*by, Y=-distance*bx), dict(
        big_to_small_base_unit=[bx,by], left_base_unit=[by,-bx],
        distance_mm=distance, distance_range_mm=shift_range)


def main(report_path):
    report_path = Path(report_path).resolve()
    raw = report_path.read_bytes()
    report = json.loads(raw)
    if report.get('status') != 'completed':
        raise TransferError('Completed calibration and Align report required.')
    capture = report['calibrated']
    target = report['after']['target']
    before, after = capture['before']['robot']['pose_mm'], capture['after']['robot']['pose_mm']
    if capture['after']['target'] != target or any(abs(before[k]-after[k]) > .05 for k in ('X','Y','Z','Rz')):
        raise TransferError('Image pose/target could not be verified.')
    previous = json.loads(PREVIOUS.read_bytes())['state']['target']
    shift = math.hypot(target['x']-previous['x'], target['y']-previous['y'])
    yaw = abs(wrap(target['rz']-previous['rz']))
    if shift > 1 or yaw > 1:
        raise TransferError('Fresh target differs by more than 1 mm/degree; measured-pose correction needs review.')
    live = get('/state')
    if live['target'] != target or live['sequence']['active']:
        raise TransferError('Fresh calibration context changed.')
    feedback_raw = FEEDBACK.read_bytes()
    feedback = json.loads(feedback_raw)
    gaps = feedback['gap_observation']
    if (feedback.get('contact_label') != 'no_contact_operator_confirmed'
            or not gaps.get('right_gap_larger') or not gaps.get('both_jaws_visibly_clear')):
        raise TransferError('Require the corrected no-contact operator observation.')
    image = Path(capture['image']).resolve()
    if image.parent != report_path.parent:
        raise TransferError('Image outside the recorded capture folder.')
    detection = sdk_detect(str(image))
    if not detection:
        raise TransferError('Both disks required in the saved calibrated image.')
    cfg = next(c for c in load_configs() if c['name'] == 'Wide')
    if abs(wrap(detection['mark'][2]-cfg['model_mark_img'][2])) > 1:
        raise TransferError('Image differs from converged disk orientation.')
    big = trans_img_pos_2_world(cfg, *detection['big_c'])
    small = trans_img_pos_2_world(cfg, *detection['small_c'])
    delta, mapping = centering_delta(big,small,before['Rz'],
                                    gaps['left_gap_mm'],gaps['right_gap_mm'])
    evidence = dict(
        schema='cephla.measured-gap-centering.v1',
        measured_pose=feedback['pose_mm'], delta_base_mm=delta, mapping=mapping,
        feedback_path=str(FEEDBACK.relative_to(ROOT)),
        feedback_sha256=hashlib.sha256(feedback_raw).hexdigest(),
        calibration_report=str(report_path.relative_to(ROOT)),
        calibration_report_sha256=hashlib.sha256(raw).hexdigest(),
        image=str(image.relative_to(ROOT)), image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
        capture_pose=before, detection=detection, big_tool_mm=big.tolist(), small_tool_mm=small.tolist(),
        camera_config=dict(name=cfg['name'],cam_in_tool_raw=cfg['cam_in_tool_raw'].tolist(),
                           cal_tab_raw=cfg['cal_tab_raw'].tolist(),cam_param=cfg['cam_param'].tolist()),
        previous_target=previous, target_difference=dict(xy_mm=shift,yaw_deg=yaw),
        assumptions=['Plate has not moved since gap measurement; same support and tool.',
                     'Gap estimates refer to parallel gripping faces, viewed from above with big disk above small.',
                     'Use measured endpoint plus offset once; no extra vision placement shift.'],
        physical_centering_verified=False, motion_sent=False)
    print(json.dumps(dict(delta_base_mm=delta, mapping=mapping,
                          fresh_target_difference=evidence['target_difference']),indent=2))
    prepare(centering=evidence)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('calibration_report')
    main(parser.parse_args().calibration_report)
