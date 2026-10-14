"""Pair Flask captures with measured depth and split by capture session."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from depth_scene import DATASET, write_json


def load_pair(rgb_path, depth_path):
    rgb = cv2.imread(str(rgb_path))
    depth = np.load(depth_path, allow_pickle=False)
    if rgb is None or depth.ndim != 2 or depth.shape != rgb.shape[:2]:
        raise ValueError('Depth must be HxW, registered pixel-for-pixel to the original RGB image')
    if not np.issubdtype(depth.dtype, np.floating):
        raise ValueError('Depth labels must be float32/float64 meters, not uint16 millimeters')
    valid = np.isfinite(depth) & (depth > 0)
    if valid.sum() < 100:
        raise ValueError('At least 100 independently measured valid depth pixels are required')
    return rgb, depth, valid


def label_sample(sample, depth_file, source):
    sample, depth_file = Path(sample).resolve(), Path(depth_file).resolve()
    if source not in ('rgbd_registered', 'calibrated_stereo', 'measured_plane'):
        raise ValueError('Choose an independent measurement source')
    if depth_file.name in ('prediction.npy', 'depth_preview.png'):
        raise ValueError('Model predictions are not ground-truth labels')
    metadata = json.loads((sample / 'metadata.json').read_text(encoding='utf-8'))
    _, depth, _ = load_pair(sample / 'rgb.png', depth_file)
    target = sample / 'depth_m.npy'
    if metadata.get('ground_truth') or target.exists():
        raise ValueError('This capture is already labeled; keep its provenance intact')
    np.save(target, depth.astype(np.float32), allow_pickle=False)
    metadata['ground_truth'] = dict(file='depth_m.npy', units='meters', source=source,
        convention='camera optical-axis Z, not Euclidean ray range',
        sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    write_json(sample / 'metadata.json', metadata)


def prepare(root, output, val_sessions, test_sessions):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not val_sessions or not test_sessions or set(val_sessions) & set(test_sessions):
        raise ValueError('Specify distinct validation and test capture sessions')
    rows = dict(train=[], val=[], test=[])
    for path in sorted(root.glob('*/*/metadata.json')):
        meta = json.loads(path.read_text(encoding='utf-8'))
        gt = meta.get('ground_truth')
        if not gt:
            continue
        if gt.get('units') != 'meters' or gt.get('source') not in ('rgbd_registered', 'calibrated_stereo', 'measured_plane'):
            raise ValueError(f'Invalid label provenance: {path}')
        rgb, depth = path.parent / 'rgb.png', path.parent / 'depth_m.npy'
        load_pair(rgb, depth)
        if hashlib.sha256(depth.read_bytes()).hexdigest() != gt.get('sha256'):
            raise ValueError(f'Label was modified after registration: {depth}')
        session = meta['session']
        split = 'val' if session in val_sessions else 'test' if session in test_sessions else 'train'
        rows[split].append(dict(rgb=str(rgb), depth_m=str(depth), session=session, source=gt['source']))
    if any(not data for data in rows.values()):
        raise ValueError('Need labeled captures in train, validation and test sessions; unlabeled images are skipped')
    output.mkdir(parents=True, exist_ok=True)
    for split, data in rows.items():
        (output / f'{split}.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in data), encoding='utf-8')
    return {name: len(data) for name, data in rows.items()}


def read_manifest(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows:
        raise ValueError('Empty training/evaluation manifest')
    for row in rows:
        load_pair(row['rgb'], row['depth_m'])
        if not row.get('session'):
            raise ValueError('Every pair needs its capture session')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    label = sub.add_parser('label')
    label.add_argument('--sample', required=True)
    label.add_argument('--depth', required=True, help='Registered HxW float32 camera-Z array in meters')
    label.add_argument('--source', required=True, choices=['rgbd_registered', 'calibrated_stereo', 'measured_plane'])
    split = sub.add_parser('prepare')
    split.add_argument('--root', default=str(DATASET))
    split.add_argument('--output', default=str(DATASET / 'manifests'))
    split.add_argument('--val-session', action='append', required=True)
    split.add_argument('--test-session', action='append', required=True)
    args = parser.parse_args()
    if args.command == 'label':
        label_sample(args.sample, args.depth, args.source)
        print('Measured label registered; original camera image preserved.')
    else:
        print(prepare(args.root, args.output, args.val_session, args.test_session))


if __name__ == '__main__':
    main()
