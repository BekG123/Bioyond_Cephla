"""Offline grid registration diagnostic. No camera/controller access or targets."""
from check_multiview_rim import ROOT, cv2, json, DetectionError
from grid_preview import fit_grid
from project_taught_disks import transform
import numpy as np


def fit(image):
    gray = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (1200, 800), interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.createCLAHE(2, (8, 8)).apply(gray), (5, 5), 1.2)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1.2, 75,
                             param1=80, param2=18, minRadius=32, maxRadius=46)
    if circles is None:
        raise DetectionError('No measured wells')
    return fit_grid(circles[0, :, :2])


if __name__ == '__main__':
    report = json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
    paths = [report['images']['target']['path']]
    base = ROOT/'operator_ui/reports/projected_disk_pilot'
    for folder in ('wider_view_validation_20261026', 'multiview_spaced_validation_20261026'):
        paths += sorted((base/folder).glob('fresh_*.jpg'))
    all_grid = np.array([[c, r] for r in range(6) for c in range(8)], float)
    previous = {}
    for path in paths:
        from pathlib import Path
        path = Path(path)
        try:
            f = fit(cv2.imread(str(path)))
            projected = transform(all_grid, f['h'])
            original = previous.setdefault(path.parent.name, projected)
            print(json.dumps(dict(image=str(path.relative_to(ROOT)), ok=True,
                wells=len(f['points']), rms=f['rmse'],
                max_stationary_grid_shift_px=float(np.linalg.norm(projected-original, axis=1).max()),
                H=f['h'].tolist())))
        except DetectionError as e:
            print(json.dumps(dict(image=str(path.relative_to(ROOT)), ok=False, error=str(e))))
