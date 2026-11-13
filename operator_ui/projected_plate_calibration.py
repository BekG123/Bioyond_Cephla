"""Shared projected-two-disk math for plate calibration. No hardware calls.

Trackers supply rim/grid-registered outlines in native camera pixels. This
module applies the same vendor Wide transform for every plate. A taught grasp
is a rigid relationship to that target, not a fresh manually added XY offset.
Virtual circle size never determines Z, force, plate identity or A1 orientation.
"""
import math
from dataclasses import dataclass
from statistics import median

import numpy as np

from autonomy import TransferError, wrap


def target_from_mark(pose, measurement, cfg):
    import teach
    current = teach.mark_in_robot_pose(cfg, measurement['mark'])
    camera = teach.new_acc_pose([pose['X'], pose['Y'], pose['Z'], 0, 0, pose['Rz']],
                               teach.tool_offset_xyrz(cfg, current))
    tool = teach.final_acc_pose(cfg, camera)
    if not np.isfinite(tool).all():
        raise TransferError('Nonfinite projected alignment target.')
    return dict(x=float(tool[0]), y=float(tool[1]), rz=float(wrap(tool[5])))


def measurement_from_outlines(outlines, pose, cfg):
    """Fit both projected outlines, then convert their mark into robot XY/yaw."""
    import teach
    if set(outlines) != {'large', 'small'}:
        raise TransferError('Both labelled virtual disks are required.')
    centers = {}
    for label, outline in outlines.items():
        p = np.asarray(outline, dtype=float)
        if p.ndim != 2 or p.shape[1] != 2 or len(p) < 3 or not np.isfinite(p).all():
            raise TransferError('Invalid projected disk outline.')
        fit, _, rank, _ = np.linalg.lstsq(
            np.column_stack([2*p, np.ones(len(p))]), np.sum(p*p, axis=1), rcond=None)
        if rank != 3 or not np.isfinite(fit).all():
            raise TransferError('Invalid projected disk center.')
        centers[label] = fit[:2]
    big, small = centers['large'], centers['small']
    if np.linalg.norm(small-big) < 1:
        raise TransferError('Projected disk centers overlap.')
    middle = (big+small)/2
    mark = [float(middle[0]), float(middle[1]),
            float(np.degrees(np.arctan2(*(small-big)[::-1])) % 360)]
    current = teach.mark_in_robot_pose(cfg, mark)
    offset = np.zeros(6)
    offset[:2] = current[:2]-cfg['model_mark_robot'][:2]
    correction = teach.new_acc_pose([pose['X'], pose['Y'], pose['Z'], 0, 0, pose['Rz']], offset)
    result = dict(mark=mark, error_xy_mm=(correction[:2]-[pose['X'], pose['Y']]).tolist(),
                  target=target_from_mark(pose, {'mark': mark}, cfg), depth_estimated=False)
    if not np.isfinite(result['error_xy_mm']).all():
        raise TransferError('Nonfinite projected centering error.')
    return result


@dataclass(frozen=True)
class PlateCalibrationProfile:
    plate_id: str
    rows: int
    columns: int
    reference_target: tuple  # x, y, rz from the accepted camera observation
    taught_endpoint: tuple  # X, Y, Z, Rz, including ALL accepted manual corrections
    grip_e1_mm: float
    min_wells: int
    max_grid_rmse_px: float = 8.
    max_center_error_mm: float = .75
    # Scope of an open-jaw candidate, NOT permission for automatic gripping.
    max_trial_shift_mm: float = 1.
    max_trial_yaw_deg: float = .5


def solve(measurements, profile):
    """Estimate one target from three bursts and transport the taught grasp once.

    T_grasp_live = T_target_live * inverse(T_target_reference) * T_grasp_taught.
    Z always comes from the plate's physically accepted profile. This result is
    a candidate: IK and physical acceptance are separate from vision quality.
    """
    if len(measurements) != 3:
        raise TransferError('Three independent plate observations are required.')
    base = dict(zip(('x', 'y', 'rz'), profile.reference_target))
    seat = dict(zip(('X', 'Y', 'Z', 'Rz'), profile.taught_endpoint))
    if not all(math.isfinite(v) for v in (*base.values(), *seat.values(), profile.grip_e1_mm)):
        raise TransferError('Nonfinite taught plate profile.')
    targets, errors, corners, yaws = [], [], [], []
    for m in measurements:
        target = m['target']
        values = [target[k] for k in ('x', 'y', 'rz')]
        count = m['measured_wells']
        if type(count) is not int or not profile.min_wells <= count <= profile.rows*profile.columns:
            raise TransferError('Measured well grid does not match the selected plate profile.')
        rim = np.asarray(m['corners_preview_px'], dtype=float)
        err = np.asarray(m['error_xy_mm'], dtype=float)
        if (rim.shape != (4, 2) or err.shape != (2,) or
                not np.isfinite([*values, m['grid_rmse_px']]).all() or
                not np.isfinite(rim).all() or not np.isfinite(err).all()):
            raise TransferError('Invalid plate measurement.')
        if not 0 <= m['grid_rmse_px'] <= profile.max_grid_rmse_px:
            raise TransferError('Well-grid residual exceeds the plate profile limit.')
        if np.linalg.norm(err) > profile.max_center_error_mm:
            raise TransferError('Plate is outside the calibrated camera centering region.')
        targets.append(values[:2]); errors.append(err); corners.append(rim)
        yaws.append(wrap(values[2]-base['rz']))
    def spread(values):
        a = np.asarray(values)
        return float(np.linalg.norm(a[:, None]-a[None, :], axis=-1).max())
    yaw_spread = max(abs(wrap(a-b)) for a in yaws for b in yaws)
    quality = dict(target_xy_spread_mm=spread(targets), xy_spread_mm=spread(errors),
                   corner_spread_preview_px=spread(corners), yaw_spread_deg=yaw_spread)
    if (quality['target_xy_spread_mm'] > .25 or quality['xy_spread_mm'] > .25 or
            quality['corner_spread_preview_px'] > .8 or yaw_spread > .2):
        raise TransferError('Stationary plate observations disagree; no alignment.')
    yaw = median(yaws)
    observed = dict(x=median(t[0] for t in targets), y=median(t[1] for t in targets),
                    rz=wrap(base['rz']+yaw))
    a = math.radians(yaw); c, s = math.cos(a), math.sin(a)
    dx, dy = seat['X']-base['x'], seat['Y']-base['y']
    endpoint = dict(X=observed['x']+c*dx-s*dy, Y=observed['y']+s*dx+c*dy,
                    Z=seat['Z'], Rz=wrap(seat['Rz']+yaw))
    distance = math.hypot(endpoint['X']-seat['X'], endpoint['Y']-seat['Y'])
    if distance > profile.max_trial_shift_mm or abs(yaw) > profile.max_trial_yaw_deg:
        raise TransferError('Measured correction exceeds the bounded open-jaw trial scope.')
    return dict(plate_id=profile.plate_id, grid=[profile.rows, profile.columns],
                measured_target=observed, reference_target=base, taught_endpoint=seat,
                endpoint=endpoint, endpoint_shift_mm=distance, yaw_delta_deg=yaw,
                grip_e1_mm=profile.grip_e1_mm, quality=quality,
                method='projected-two-disks-vendor-wide+taught-rigid-grasp-v1',
                depth_estimated=False, correction_applied_once=True,
                physical_acceptance='pending', grip_authorized=False)
