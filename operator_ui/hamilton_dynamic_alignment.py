"""Camera-to-Prep registration and alignment previews; no hardware writes.

All coordinates are millimeters. A camera calibration is not assumed to be a
controller calibration. Register independently measured reference points before
producing controller targets. Pickup depth is intentionally not inferred here.
"""
import hashlib
import json
from datetime import datetime, timezone
import numpy as np


class AlignmentError(ValueError):
    pass


def points(value, minimum=1):
    result = np.asarray(value, dtype=float)
    if result.ndim != 2 or result.shape[1] != 3 or len(result) < minimum or not np.isfinite(result).all():
        raise AlignmentError('Expected finite XYZ reference points in millimeters.')
    return result


def fit_registration(camera_fit, controller_fit, camera_check, controller_check,
                     *, serial, calibration_sha256, evidence):
    """Rigid registration from measured pairs, with separate held-out references.

    Four or more noncoplanar fit points constrain the 3-D origin and axes.
    Two independent check points must each agree within 0.5 mm. Evidence must
    identify the physical references; synthetic/simulated fits are not live proof.
    """
    a, b = points(camera_fit, 4), points(controller_fit, 4)
    ca, cb = points(camera_check, 2), points(controller_check, 2)
    if a.shape != b.shape or ca.shape != cb.shape:
        raise AlignmentError('Reference pairs have different sizes.')
    if np.min(np.linalg.norm(ca[:,None,:]-a[None,:,:],axis=2)) < 1:
        raise AlignmentError('Check references must be independent of the fit points.')
    if np.linalg.matrix_rank(a - a.mean(axis=0), tol=0.1) < 3:
        raise AlignmentError('References must span X, Y and Z.')
    if not serial or len(calibration_sha256) != 64 or not evidence:
        raise AlignmentError('Instrument, camera calibration hash and reference evidence are required.')
    u, _, vt = np.linalg.svd((a-a.mean(axis=0)).T @ (b-b.mean(axis=0)))
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        raise AlignmentError('Reference handedness disagrees; check axes and point identities.')
    translation = b.mean(axis=0) - rotation @ a.mean(axis=0)
    residual = np.linalg.norm((rotation @ a.T).T + translation - b, axis=1)
    check = np.linalg.norm((rotation @ ca.T).T + translation - cb, axis=1)
    if max(residual.max(), check.max()) > .5:
        raise AlignmentError('Registration fails the 0.5 mm reference agreement requirement.')
    return {
        'serial': serial, 'calibration_sha256': calibration_sha256,
        'rotation': rotation.tolist(), 'translation_mm': translation.tolist(),
        'fit_errors_mm': residual.tolist(), 'check_errors_mm': check.tolist(),
        'reference_evidence': evidence, 'physical_validation_complete': False,
        'camera_fit_mm': a.tolist(), 'controller_fit_mm': b.tolist(),
        'camera_check_mm': ca.tolist(), 'controller_check_mm': cb.tolist(),
    }


def controller_points(camera_points, registration, *, serial, calibration_sha256):
    if registration.get('serial') != serial or registration.get('calibration_sha256') != calibration_sha256:
        raise AlignmentError('Registration belongs to another instrument or camera calibration.')
    # Recompute from evidence, rather than trusting editable cached matrices/errors.
    verified = fit_registration(
        registration['camera_fit_mm'], registration['controller_fit_mm'],
        registration['camera_check_mm'], registration['controller_check_mm'],
        serial=serial, calibration_sha256=calibration_sha256,
        evidence=registration.get('reference_evidence'))
    if registration.get('physical_validation_complete') is not True:
        raise AlignmentError('Registration has not passed physical validation.')
    return (np.asarray(verified['rotation']) @ points(camera_points).T).T + verified['translation_mm']


# Watchdog drives the door actuator; set True to restore the door blocker.
DOOR_INTERLOCK = False


def alignment_preview(estimate, probe, registration=None, *, now=None):
    """Build a bounded two-opening preview from a fresh capture, never a move."""
    now = now or datetime.now(timezone.utc)
    timestamp = datetime.fromisoformat(probe['time_utc'])
    age = (now - timestamp).total_seconds()
    blockers = []
    if not 0 <= age <= 60:
        blockers.append('Capture is older than 60 seconds or has an invalid timestamp.')
    if estimate['tip_rims_used'] < 50 or estimate['pose_reprojection_rms_pixels'] > 2:
        blockers.append('Tip-grid image quality is insufficient.')
    if estimate['crop_registration_inliers'] < 50 or estimate['crop_registration_rms_pixels'] > .7:
        blockers.append('Camera crop registration is insufficient.')
    if probe.get('tip_rack_site') != 4:
        blockers.append('This capture workflow is configured for the current rack at site 4.')
    after = probe.get('http_after', {})
    if 'Serial Number: PRPGD2427' not in after.get('instruments/connection-info', []):
        blockers.append('Instrument identity is not confirmed after capture.')
    if probe.get('tcp_queries', {}).get('PrepGetIsInitialized', {}).get('value') is not True:
        blockers.append('Controller initialization is not confirmed.')
    if after.get('instruments/global-run-state') != 'Idle':
        blockers.append('Hamilton is not confirmed Idle after capture.')
    if DOOR_INTERLOCK and after.get('service-software-api/sensor-status', {}).get('isDoorClosed') is not True:
        blockers.append('Door is not confirmed closed.')
    selected = []
    for index in estimate['selected_preview_openings']:
        point = next(p for p in estimate['grid_points'] if p['column'] == index['column'] and p['row'] == index['row'])
        if not point['observed']:
            blockers.append('A selected tip opening was inferred, not observed.')
        selected.append(point)
    mapped = None
    if registration is None:
        blockers.append('No physically verified camera-to-controller registration.')
    else:
        try:
            mapped = controller_points([p['exported_frame_xyz_mm'] for p in selected], registration,
                serial='PRPGD2427', calibration_sha256=estimate['calibration_sha256']).tolist()
        except (AlignmentError, KeyError, TypeError) as error:
            blockers.append(str(error))
    bounds = {b['channel']: b for b in probe.get('tcp_queries', {}).get('PrepGetChannelBounds', {}).get('bounds', [])}
    targets = None
    if mapped is not None:
        # Higher Y belongs to the rear channel. X targets can differ: do not
        # average them and assume both nozzles can pick up a rotated rack at once.
        ordered = sorted(zip(mapped, selected), key=lambda pair: pair[0][1], reverse=True)
        targets = []
        for channel, (xyz, opening) in zip((2, 1), ordered):
            limit = bounds.get(channel)
            if limit is None or any(not limit[f'{axis}_min'] <= xyz[i] <= limit[f'{axis}_max'] for i,axis in enumerate('xyz')):
                blockers.append(f'Opening for firmware channel {channel} lacks valid travel bounds.')
            targets.append({'firmware_channel':channel, 'opening_xyz_mm':xyz,
                            'image_grid_index':[opening['column'],opening['row']]})
    blockers.append('Direct-driver stop/interlock behavior and tip seating depth are not commissioned.')
    return {'kind':'alignment_preview', 'serial':'PRPGD2427', 'capture_age_s':round(age,2),
            'tip_rack_site':4, 'plate_site':8, 'selected_openings':selected,
            'controller_opening_targets':targets, 'pickup_depth_mm':None,
            'executable':False, 'motion_sent':False, 'blockers':blockers,
            'capture_digest':hashlib.sha256(json.dumps(probe,sort_keys=True).encode()).hexdigest()}
