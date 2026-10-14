"""Local scene depth and lossless dataset capture. No robot commands or solvers."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

import cv2
import numpy as np

from depth_model import CHECKPOINT, REPO, SOURCE_COMMIT, build_model

HERE = Path(__file__).resolve().parent
DATASET = HERE / 'datasets' / 'depth'


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')


class DepthScene:
    def __init__(self, checkpoint=None):
        self.checkpoint = Path(checkpoint or os.environ.get('BIOYOND_DEPTH_CHECKPOINT', CHECKPOINT))
        self.model = None
        self.device = None
        self.kind = 'relative_inverse_depth'
        self.units = 'arbitrary'
        self.lock = threading.Lock()
        self.sha256 = None

    def public(self):
        return dict(name='Depth Anything V2 Small', parameters='24.8M',
                    installed=(REPO / 'depth_anything_v2/dpt.py').is_file()
                    and self.checkpoint.is_file() and importlib.util.find_spec('torch') is not None,
                    loaded=self.model is not None, device=self.device,
                    kind=self.kind, units=self.units)

    def _load(self):
        if self.model is not None:
            return
        if not self.checkpoint.is_file():
            raise RuntimeError('Depth checkpoint missing; run operator_ui/setup_depth.ps1')
        import torch
        state = torch.load(self.checkpoint, map_location='cpu', weights_only=True)
        metric = isinstance(state, dict) and state.get('format') == 'bioyond_metric_v1'
        model = build_model(metric=metric, max_depth=state['max_depth_m'] if metric else 2.)
        model.load_state_dict(state['model'] if metric else state, strict=True)
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.model = model.to(self.device).eval()
        self.kind = 'estimated_metric_depth' if metric else 'relative_inverse_depth'
        self.units = 'meters (model estimate, unverified)' if metric else 'arbitrary'
        self.sha256 = hashlib.sha256(self.checkpoint.read_bytes()).hexdigest()

    def infer(self, frame):
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError('Expected a BGR camera image')
        with self.lock:
            self._load()
            start = time.perf_counter()
            # 518 is upstream's default; model remains cached across requests.
            depth = np.asarray(self.model.infer_image(frame, input_size=518), dtype=np.float32)
            elapsed = time.perf_counter() - start
        if depth.shape != frame.shape[:2] or not np.isfinite(depth).all():
            raise RuntimeError('Invalid depth map; result discarded')
        lo, hi = np.percentile(depth, [2, 98])
        normalized = np.clip((depth - lo) / max(float(hi - lo), 1e-6), 0, 1)
        preview = cv2.applyColorMap((normalized * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
        return depth, preview, dict(model='Depth Anything V2 Small', encoder='vits',
            source_commit=SOURCE_COMMIT, checkpoint_sha256=self.sha256,
            kind=self.kind, units=self.units, inference_seconds=round(elapsed, 3),
            device=self.device, input_size=518, map_shape=list(depth.shape),
            p02=float(lo), median=float(np.median(depth)), p98=float(hi),
            interpretation=('Higher values generally mean nearer; colors normalized per image.'
                            if self.kind == 'relative_inverse_depth' else
                            'Metric estimates require held-out validation on this camera.'),
            calibrated_intrinsics=False, robot_motion_authorized=False)


def capture_sample(frame, session, pose_before, pose_after, camera_info, root=DATASET):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', session):
        raise ValueError('Session must use 1-48 letters, numbers, underscores or hyphens')
    sample_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:10]
    folder = Path(root) / session / sample_id
    folder.mkdir(parents=True, exist_ok=False)
    if not cv2.imwrite(str(folder / 'rgb.png'), frame):
        raise RuntimeError('Cannot save training capture')
    calibration = HERE.parent / 'grab_skill/calibration.json'
    snapshot = json.loads(calibration.read_text(encoding='utf-8-sig')) if calibration.exists() else None
    metadata = dict(schema=1, id=sample_id, session=session,
        captured_utc=datetime.now(timezone.utc).isoformat(), rgb='rgb.png',
        width=frame.shape[1], height=frame.shape[0], color_storage='RGB PNG (OpenCV writes BGR)',
        robot_pose_before_mm=pose_before, robot_pose_after_mm=pose_after,
        pose_synchronized=False, camera=camera_info, calibration_snapshot=snapshot,
        ground_truth=None, prediction_is_ground_truth=False)
    write_json(folder / 'metadata.json', metadata)
    return folder, metadata


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Run local scene depth on a saved camera image')
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    frame = cv2.imread(args.image)
    depth, preview, report = DepthScene().infer(frame)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    np.save(output / 'prediction.npy', depth, allow_pickle=False)
    if not cv2.imwrite(str(output / 'depth_preview.png'), preview):
        raise RuntimeError('Cannot write preview')
    write_json(output / 'report.json', report)
    print(json.dumps(report))
