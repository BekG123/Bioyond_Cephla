"""Bounded empty-arm HOME start for slot-1 retrieval, not contact/arrival checks.

Keep height within the original 0.05 mm band. The horizontal/yaw limits are
narrower than RobotService's general 1 mm / 0.5 degree arrival tolerances.
Routes must still be validated from the measured pose and joint winding.
"""
import math

from autonomy import TransferError, wrap

XY_TOL_MM = .5
Z_TOL_MM = .05
YAW_TOL_DEG = .2


def check_home_start(actual, target):
    keys = ('X', 'Y', 'Z', 'Rz')
    if any(type(p.get(k)) not in (int, float) or not math.isfinite(p[k])
           for p in (actual, target) for k in keys):
        raise TransferError('HOME start requires finite measured pose feedback.')
    xy = math.hypot(actual['X'] - target['X'], actual['Y'] - target['Y'])
    z = abs(actual['Z'] - target['Z'])
    yaw = abs(wrap(actual['Rz'] - target['Rz']))
    if xy > XY_TOL_MM + 1e-9 or z > Z_TOL_MM + 1e-9 or yaw > YAW_TOL_DEG + 1e-9:
        raise TransferError(
            f'Arm is outside HOME clearance start tolerance: XY {xy:.3f} mm '
            f'(limit {XY_TOL_MM}), Z {z:.3f} mm (limit {Z_TOL_MM}), '
            f'Rz {yaw:.3f} degrees (limit {YAW_TOL_DEG}). '
            f'Measured: {actual}; required reference: {target}. '
            'Use the checked HOME return first.')
