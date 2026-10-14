"""Real-model plumbing check on SYNTHETIC labels, never a usable calibration.

Run explicitly with .venv-depth/Scripts/python.exe. Artifacts are temporary.
"""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from depth_scene import capture_sample, DepthScene
from depth_dataset import label_sample, prepare
from train_depth import main


def smoke():
    with tempfile.TemporaryDirectory(prefix='depth_training_smoke_') as directory:
        root = Path(directory)
        frame = np.zeros((56, 84, 3), np.uint8)
        frame[10:45, 20:60] = 180
        measurement = root / 'synthetic_fixture_m.npy'
        np.save(measurement, np.full(frame.shape[:2], .3, np.float32))
        for session in ('synthetic_train', 'synthetic_val', 'synthetic_test'):
            folder, _ = capture_sample(frame, session, None, None, {}, root / 'data')
            label_sample(folder, measurement, 'measured_plane')
        manifests = root / 'manifests'
        prepare(root / 'data', manifests, ['synthetic_val'], ['synthetic_test'])
        output = root / 'run'
        with patch.object(sys, 'argv', ['train_depth', '--train', str(manifests / 'train.jsonl'),
                '--val', str(manifests / 'val.jsonl'), '--output', str(output),
                '--epochs', '1', '--image-size', '56']):
            main()
        assert (output / 'best.pt').is_file()
        with patch.object(sys, 'argv', ['train_depth', '--evaluate', str(manifests / 'test.jsonl'),
                '--checkpoint', str(output / 'best.pt'), '--image-size', '56']):
            main()
        depth, _, report = DepthScene(output / 'best.pt').infer(frame)
        assert report['kind'] == 'estimated_metric_depth'
        assert depth.shape == frame.shape[:2] and np.isfinite(depth).all()
        assert (depth >= 0).all() and (depth <= 2).all()
        print(json.dumps(dict(smoke='passed', data='synthetic only', deployment='none')))


if __name__ == '__main__':
    smoke()
