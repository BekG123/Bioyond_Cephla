"""Save pretrained depth outputs for a completed capture session; no hardware."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from depth_scene import DepthScene, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    args = parser.parse_args()
    ledger = json.loads((args.session / 'collection.json').read_text())
    if ledger.get('state') != 'complete':
        raise ValueError('Finish image collection before preparing its baseline')
    model = DepthScene()
    model._load()
    if model.kind != 'relative_inverse_depth':
        raise ValueError('This baseline requires the original relative-depth checkpoint')
    records, tiles = [], []
    selected = {0, 12, 16, 20, 24}
    for sample in ledger['samples']:
        folder = Path(sample['sample'])
        if (folder / 'prediction.npy').exists():
            raise ValueError(f'Existing prediction preserved; refusing overwrite: {folder}')
        frame = cv2.imread(str(folder / 'rgb.png'))
        depth, preview, report = model.infer(frame)
        np.save(folder / 'prediction.npy', depth, allow_pickle=False)
        if not cv2.imwrite(str(folder / 'depth_preview.png'), preview):
            raise RuntimeError('Cannot save depth preview')
        metadata = json.loads((folder / 'metadata.json').read_text())
        metadata['prediction'] = dict(array='prediction.npy', preview='depth_preview.png', **report)
        write_json(folder / 'metadata.json', metadata)
        record = dict(index=sample['index'], sample=str(folder), pose=sample['pose'],
                      rgb_sha256=hashlib.sha256((folder / 'rgb.png').read_bytes()).hexdigest(),
                      prediction_sha256=hashlib.sha256((folder / 'prediction.npy').read_bytes()).hexdigest(),
                      prediction=report)
        records.append(record)
        print(json.dumps(dict(done=len(records), total=len(ledger['samples']),
                              inference_seconds=report['inference_seconds'])), flush=True)
        if sample['index'] in selected:
            row = np.full((315, 840, 3), 25, np.uint8)
            row[35:315, :420] = cv2.resize(frame, (420, 280))
            row[35:315, 420:] = cv2.resize(preview, (420, 280))
            dx, dy = metadata['collection']['offset_mm']
            cv2.putText(row, f'View {sample["index"]+1}: dX={dx:+} dY={dy:+} mm',
                        (10, 24), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,255,255), 1)
            cv2.putText(row, 'Pretrained relative depth', (435,24), cv2.FONT_HERSHEY_SIMPLEX,
                        .55, (255,255,255), 1)
            tiles.append(row)
    output = dict(model_checkpoint_sha256=model.sha256, captures=records,
                  training_started=False, measured_depth_labels=0,
                  note='One XY capture session. Depth values are relative, not metric labels. '
                       'Each preview has its own color normalization.')
    write_json(args.session / 'pretrained_baseline.json', output)
    if not cv2.imwrite(str(args.session / 'capture_depth_overview.jpg'), np.concatenate(tiles, axis=0)):
        raise RuntimeError('Cannot save overview')
    print(json.dumps(dict(saved=str(args.session / 'pretrained_baseline.json'),
                          overview=str(args.session / 'capture_depth_overview.jpg'))), flush=True)


if __name__ == '__main__':
    main()
