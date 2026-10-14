"""Single-GPU/CPU metric fine-tuning on measured Flask image/depth pairs.

Windows-friendly adaptation of upstream metric_depth/train.py: a Small encoder,
metric DPT head, masked log-depth loss and validation MAE. Never trains on the
model's own relative-depth predictions. Training does not import Flask/hardware.
"""
import argparse
import json
from pathlib import Path
import random

import cv2
import numpy as np

from depth_dataset import read_manifest, load_pair
from depth_model import CHECKPOINT, SOURCE_COMMIT, build_model
from training_progress import TrainingProgress


def reject_leakage(train, val):
    if {r['session'] for r in train} & {r['session'] for r in val}:
        raise ValueError('Train/validation sessions overlap; split whole sessions')
    if {str(Path(r['rgb']).resolve()) for r in train} & {str(Path(r['rgb']).resolve()) for r in val}:
        raise ValueError('Train/validation images overlap')


def tensor_pair(row, image_size, max_depth, device):
    import torch
    image, depth, valid = load_pair(row['rgb'], row['depth_m'])
    h, w = depth.shape
    scale = image_size / min(h, w)
    size = (int(round(w * scale / 14) * 14), int(round(h * scale / 14) * 14))
    rgb = cv2.cvtColor(cv2.resize(image, size, interpolation=cv2.INTER_CUBIC), cv2.COLOR_BGR2RGB) / 255.
    rgb = ((rgb - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).astype(np.float32)
    depth = cv2.resize(np.where(valid, depth, 0).astype(np.float32), size, interpolation=cv2.INTER_NEAREST)
    mask = np.isfinite(depth) & (depth > .001) & (depth < max_depth)
    if mask.sum() < 100:
        raise ValueError('Too few labels in configured depth range after resizing')
    return (torch.from_numpy(rgb.transpose(2, 0, 1).copy()).unsqueeze(0).to(device),
            torch.from_numpy(depth).unsqueeze(0).to(device),
            torch.from_numpy(mask).unsqueeze(0).to(device))


def evaluate(model, rows, device, image_size, max_depth, progress=None):
    import torch
    total_abs, total_sq, total_relative, count = 0., 0., 0., 0
    with torch.inference_mode():
        model.eval()
        for index, row in enumerate(rows):
            image, target, mask = tensor_pair(row, image_size, max_depth, device)
            pred = model(image)
            error = pred[mask] - target[mask]
            total_abs += error.abs().sum().item()
            total_sq += error.square().sum().item()
            total_relative += (error.abs() / target[mask]).sum().item()
            count += error.numel()
            if progress is not None:
                progress.update(validation_step=index + 1, validation_steps=len(rows))
    return dict(mae_mm=1000 * total_abs / count, rmse_mm=1000 * (total_sq / count)**.5,
                abs_rel=total_relative / count, valid_pixels=count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train', help='train.jsonl')
    parser.add_argument('--val', help='val.jsonl')
    parser.add_argument('--evaluate', help='Held-out test.jsonl; requires --checkpoint')
    parser.add_argument('--checkpoint', help='Saved metric checkpoint for evaluation only')
    parser.add_argument('--pretrained', default=str(CHECKPOINT))
    parser.add_argument('--output', default='operator_ui/depth_runs/small_metric')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--image-size', type=int, default=518)
    parser.add_argument('--max-depth', type=float, default=2.)
    parser.add_argument('--lr', type=float, default=5e-5)
    parser.add_argument('--unfreeze-encoder', action='store_true')
    parser.add_argument('--check-only', action='store_true', help='Validate data without training')
    parser.add_argument('--synthetic-check', action='store_true', help='Label this run as synthetic testing, not camera calibration')
    args = parser.parse_args()
    if args.epochs < 1 or args.image_size < 56 or args.image_size % 14 or args.max_depth <= .001 or args.lr <= 0:
        parser.error('Need epochs>=1, image size multiple of 14 (>=56), positive depth/lr')
    with TrainingProgress(args.output, args.epochs, synthetic=args.synthetic_check,
                          enabled=not args.check_only and not args.evaluate) as progress:
        return run(args, parser, progress)


def run(args, parser, progress):
    progress.update(status='validating_data')
    if args.evaluate:
        if not args.checkpoint:
            parser.error('--evaluate requires --checkpoint')
        rows = read_manifest(args.evaluate)
        train, val = [], []
    else:
        if not args.train or not args.val:
            parser.error('Provide --train and --val, or --evaluate and --checkpoint')
        train, val = read_manifest(args.train), read_manifest(args.val)
        reject_leakage(train, val)
        rows = train + val
    if args.check_only:
        print(json.dumps(dict(validated_pairs=len(rows), train=len(train), val=len(val))))
        return
    progress.update(status='loading_model', train_samples=len(train), val_samples=len(val),
                    image_size=args.image_size, max_depth_m=args.max_depth)
    import torch
    torch.manual_seed(42)
    random.seed(42)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    progress.update(device=device, gpu=torch.cuda.get_device_name(0) if device == 'cuda' else None)
    if args.evaluate:
        checkpoint = torch.load(args.checkpoint, map_location='cpu', weights_only=True)
        if checkpoint.get('format') != 'bioyond_metric_v1':
            raise ValueError('Expected a metric fine-tuning checkpoint')
        if {r['session'] for r in rows} & set(checkpoint['train_sessions'] + checkpoint['val_sessions']):
            raise ValueError('Test sessions overlap training/validation sessions')
        model = build_model(metric=True, max_depth=checkpoint['max_depth_m']).to(device)
        model.load_state_dict(checkpoint['model'], strict=True)
        print(json.dumps(evaluate(model, rows, device, args.image_size, checkpoint['max_depth_m'])))
        return
    model = build_model(metric=True, max_depth=args.max_depth).to(device)
    pretrained = torch.load(args.pretrained, map_location='cpu', weights_only=True)
    encoder = {k.removeprefix('pretrained.'): v for k, v in pretrained.items() if k.startswith('pretrained.')}
    model.pretrained.load_state_dict(encoder, strict=True)
    if not args.unfreeze_encoder:
        model.pretrained.requires_grad_(False)
    optimizer = torch.optim.AdamW([
        {'params': [p for n, p in model.named_parameters() if p.requires_grad and n.startswith('pretrained.')], 'lr': args.lr / 10},
        {'params': [p for n, p in model.named_parameters() if p.requires_grad and not n.startswith('pretrained.')], 'lr': args.lr}], weight_decay=.01)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'best.pt').exists():
        raise ValueError('Output already contains best.pt; use a new run directory')
    best = float('inf')
    for epoch in range(args.epochs):
        progress.update(status='training', epoch=epoch + 1, step=0, steps=len(train))
        model.train()
        if not args.unfreeze_encoder:
            model.pretrained.eval()
        order = list(train)
        random.shuffle(order)
        losses = []
        for step, row in enumerate(order):  # Batch size 1 preserves each image's aspect ratio.
            image, target, mask = tensor_pair(row, args.image_size, args.max_depth, device)
            optimizer.zero_grad(set_to_none=True)
            pred = model(image)
            difference = target[mask].log() - pred[mask].clamp_min(1e-6).log()
            loss = (difference.square().mean() - .5 * difference.mean().square()).clamp_min(1e-8).sqrt()
            if not torch.isfinite(loss):
                raise ValueError('Non-finite loss; inspect labels')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
            optimizer.step()
            losses.append(loss.item())
            progress.update(step=step + 1, loss=float(np.mean(losses)))
        progress.update(status='validating', validation_step=0, validation_steps=len(val))
        metrics = evaluate(model, val, device, args.image_size, args.max_depth, progress)
        report = dict(epoch=epoch + 1, loss=float(np.mean(losses)), **metrics)
        print(json.dumps(report), flush=True)
        with (out / 'history.jsonl').open('a', encoding='utf-8') as file:
            file.write(json.dumps(report) + '\n')
        if metrics['mae_mm'] < best:
            best = metrics['mae_mm']
            progress.update(status='saving_checkpoint')
            torch.save(dict(format='bioyond_metric_v1', model=model.state_dict(),
                max_depth_m=args.max_depth, image_size=args.image_size, source_commit=SOURCE_COMMIT,
                train_sessions=sorted({r['session'] for r in train}),
                val_sessions=sorted({r['session'] for r in val}), validation=report,
                synthetic_check=args.synthetic_check), out / 'best.pt')
            progress.update(checkpoint=str((out / 'best.pt').resolve()), best_mae_mm=best)
        progress.update(history=progress.state['history'] + [report], **report)
    print('Saved best.pt. Evaluate on the held-out test session before using metric estimates.')


if __name__ == '__main__':
    main()
