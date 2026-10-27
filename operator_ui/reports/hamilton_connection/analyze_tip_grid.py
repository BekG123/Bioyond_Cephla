"""Offline image-space estimate only; not a robot offset or calibration."""
import json
from pathlib import Path
import cv2
import numpy as np

root = Path(__file__).parent
overlay = cv2.imread(str(root / 'site3_grid_assumed75.png'), 0)
plain = cv2.imread(str(root / 'site3_plain_assumed75.png'), 0)
assert overlay.shape == plain.shape

def groups(values):
    return [float(np.mean(g)) for g in np.split(values, np.where(np.diff(values) > 1)[0]+1) if len(g)]

# The vendor overlay draws cell boundaries, not crosshairs on openings.
x_lines = groups(np.flatnonzero(np.mean(overlay[45:497] >= 250, axis=0) > .97))
y_lines = groups(np.flatnonzero(np.mean(overlay[:, 65:746] >= 250, axis=1) > .97))
x_lines = np.array([v for v in x_lines if 50 < v < 760])
y_lines = np.array([v for v in y_lines if 30 < v < 510])
assert len(x_lines) == 13 and len(y_lines) == 9, (x_lines, y_lines)
xs = (x_lines[1:] + x_lines[:-1])/2
ys = (y_lines[1:] + y_lines[:-1])/2

# Restrict detection to the outer rims, rather than the smaller bright filters.
circles = cv2.HoughCircles(cv2.GaussianBlur(plain, (5,5), 1),
    cv2.HOUGH_GRADIENT, 1, 40, param1=80, param2=24, minRadius=20, maxRadius=27)[0]
points = []
for x, y, radius in circles:
    col, row = int(np.argmin(abs(xs-x))), int(np.argmin(abs(ys-y)))
    if np.hypot(xs[col]-x, ys[row]-y) < 25:
        points.append((col, row, float(x), float(y)))
points = np.array(points)
design = np.c_[points[:, :2], np.ones(len(points))]
keep = np.ones(len(points), dtype=bool)
for _ in range(4):
    fit = np.linalg.lstsq(design[keep], points[keep, 2:], rcond=None)[0]
    residuals = np.linalg.norm(design @ fit - points[:, 2:], axis=1)
    keep = residuals < 3
center = np.array([5.5,3.5,1]) @ fit
expected_center = np.array([np.mean(xs),np.mean(ys)])
pitch = np.array([np.mean(np.diff(xs)),np.mean(np.diff(ys))])
result = {
    'purpose': 'Exploratory image-space comparison; do not execute as robot correction',
    'operator_metal_deck_to_opening_mm': 75,
    'api_zHeight_assumed_mm': 75,
    'height_reference_equivalence_verified': False,
    'outer_rim_candidates': len(circles), 'lattice_inliers': int(keep.sum()),
    'expected_pitch_pixels': pitch.tolist(),
    'observed_column_step_pixels': fit[0].tolist(),
    'observed_row_step_pixels': fit[1].tolist(),
    'grid_center_displacement_image_pixels': (center-expected_center).tolist(),
    'rms_inlier_fit_pixels': float(np.sqrt(np.mean(residuals[keep]**2))),
    'note': 'Rim detection, perspective, and the unknown deck/API height reference limit accuracy. Image axes are not verified robot axes. A fit residual measures internal consistency, not absolute accuracy.'
}
(root/'tip_grid_image_analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
