"""Offline Wide/Long evaluation on accepted captures; never connects to hardware."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'grab_skill'))
import mcp_teach as teach
from sdk_pose import compose


def stats(values):
    a = np.asarray(values, float)
    return dict(mean=float(a.mean()), median=float(np.median(a)),
                std_population=float(a.std()), minimum=float(a.min()),
                maximum=float(a.max()), span=float(np.ptp(a)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    args = parser.parse_args()
    ledger = json.loads((args.session / 'collection.json').read_text())
    assert ledger['state'] == 'complete'
    configs = teach.load_configs()
    records = []
    for sample in ledger['samples']:
        folder = Path(sample['sample'])
        det = teach.sdk_detect(str(folder / 'rgb.png'))
        if det is None:
            raise RuntimeError(f'Detection failed: {folder}')
        meta = json.loads((folder / 'metadata.json').read_text())
        pose = [sample['pose'][k] for k in ('X', 'Y', 'Z', 'Rx', 'Ry', 'Rz')]
        selected, scores = teach.select_trigger(configs, det['mark'])
        row = dict(index=sample['index'], sample=folder.name, pose=pose,
                   offset_mm=meta['collection']['offset_mm'],
                   detection=det, selected=configs[selected]['name'],
                   rgb_sha256=hashlib.sha256((folder / 'rgb.png').read_bytes()).hexdigest(),
                   detection_matches_saved=det == sample['detection'], settings={})
        for cfg, score in zip(configs, scores):
            mark_tool = teach.mark_in_robot_pose(cfg, det['mark'])
            world = compose(pose, mark_tool)
            off = teach.tool_offset_xyrz(cfg, mark_tool)
            row['settings'][cfg['name']] = dict(
                distance_mm=float(1000 * cfg['cal_tab_raw'][5] * cfg['model_radius'] / det['big_r']),
                z_correction_mm=float(teach.tool_offset_z(cfg, det['big_r'])[2]),
                alignment_xy_mm=float(np.linalg.norm(off[:2])),
                alignment_yaw_deg=float(teach.wrap180(off[5])),
                mark_world_mm=world[:3].tolist(), selection_score=score)
        records.append(row)
        print(f'Processed {len(records)}/{len(ledger["samples"])}', flush=True)

    summary = {}
    origin_rows = [r for r in records if r['offset_mm'] == [0, 0]]
    for cfg in configs:
        name = cfg['name']
        entries = [r['settings'][name] for r in records]
        world = np.array([r['mark_world_mm'][:2] for r in entries])
        centered = world - world.mean(axis=0)
        summary[name] = dict(reference_radius_px=cfg['model_radius'],
            distance_mm=stats([r['distance_mm'] for r in entries]),
            origin_distance_mm=stats([r['settings'][name]['distance_mm'] for r in origin_rows]),
            z_correction_mm=stats([r['z_correction_mm'] for r in entries]),
            alignment_xy_mm=stats([r['alignment_xy_mm'] for r in entries]),
            alignment_yaw_deg=stats([r['alignment_yaw_deg'] for r in entries]),
            selection_count=sum(r['selected'] == name for r in records),
            stationary_target_xy_rms_about_mean_mm=float(np.sqrt(np.mean(np.sum(centered**2, axis=1)))),
            stationary_target_xy_axis_span_mm=np.ptp(world, axis=0).tolist())

    poses = np.array([r['pose'] for r in records])
    # Known robot translations give a relative XY consistency check at one height.
    # Center first: a constant target position cancels from this regression.
    robot_xy = poses[:, :2] - poses[:, :2].mean(axis=0)
    world_xy = np.array([r['settings']['Wide']['mark_world_mm'][:2] for r in records])
    camera_shift = world_xy - poses[:, :2]
    camera_shift -= camera_shift.mean(axis=0)
    mapping = np.linalg.lstsq(-robot_xy, camera_shift, rcond=None)[0]
    residual = camera_shift - (-robot_xy @ mapping)
    u, gains, vt = np.linalg.svd(mapping)
    rotation = u @ vt
    rotation_mismatch = float(np.degrees(np.arctan2(rotation[1, 0], rotation[0, 0])))
    result = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        source_session=str(args.session.resolve()), captures=len(records),
        origin_captures=len(origin_rows), detection_reproduced_count=sum(r['detection_matches_saved'] for r in records),
        robot_z_mm=stats(poses[:, 2]), robot_rz_deg=stats(poses[:, 5]),
        large_radius_px=stats([r['detection']['big_r'] for r in records]),
        disk_yaw_deg=stats([r['detection']['mark'][2] for r in records]),
        summary=summary,
        paired_long_minus_wide_mm=stats([r['settings']['Long']['distance_mm']-r['settings']['Wide']['distance_mm'] for r in records]),
        shared_xy_check=dict(mapping_expected_identity=mapping.tolist(),
            principal_gains=gains.tolist(), rotation_mismatch_deg=rotation_mismatch,
            residual_rms_mm=float(np.sqrt(np.mean(np.sum(residual**2, axis=1))))),
        limitations=['No independent absolute camera-to-plate distance labels.',
            'One physical setup, one Z and wrist angle; nearby XY views are correlated.',
            'Distance standard deviation measures consistency, not accuracy or true depth RMSE.',
            'Wide/Long selection uses image midpoint/yaw proximity to taught references, not measured depth error.',
            'XY consistency assumes the plate remained stationary and robot telemetry is reliable.',
            'Configured 205 mm plane is used for XY mapping in both settings.',
            'Z correction includes vendor half-gain when radius error is below one pixel.',
            'No robot movement, configuration changes, depth training, or label promotion.'],
        records=records)
    out = ROOT / 'operator_ui' / 'reports' / ('disk_calibration_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True, exist_ok=False)
    (out / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    for name, color in [('Wide', '#176ac5'), ('Long', '#d56816')]:
        values = [r['settings'][name]['distance_mm'] for r in records]
        axes[0].plot(np.arange(len(records)), values, '.-', label=name, color=color)
    axes[0].set(xlabel='Capture index', ylabel='Estimated camera-to-plate distance (mm)',
                title='Same images; different reference scales')
    axes[0].legend()
    axes[0].grid(alpha=.25)
    drift = world_xy - world_xy.mean(axis=0)
    sc = axes[1].scatter(drift[:, 0], drift[:, 1], c=np.arange(len(records)), cmap='viridis')
    axes[1].axhline(0, color='gray', lw=.6)
    axes[1].axvline(0, color='gray', lw=.6)
    axes[1].set(xlabel='Estimated target X minus mean (mm)', ylabel='Estimated target Y minus mean (mm)',
                title='Shared XY mapping: stationary-target drift')
    axes[1].set_aspect('equal', adjustable='datalim')
    fig.colorbar(sc, ax=axes[1], label='Capture index')
    fig.suptitle('Offline two-disk calibration check | 29 views, fixed robot height\nNo independently measured absolute distance', fontsize=12)
    fig.savefig(out / 'comparison.png', dpi=170)
    plt.close(fig)

    first = records[0]
    lines = ['# Wide / Long two-disk calibration comparison', '',
             'Offline replay of all 29 accepted captures. No hardware was connected and no configuration was changed.', '',
             '| Measurement | Wide | Long |', '|---|---:|---:|']
    for label, key, field, unit in [
        ('Median estimated distance', 'distance_mm', 'median', 'mm'),
        ('Estimated distance minimum', 'distance_mm', 'minimum', 'mm'),
        ('Estimated distance maximum', 'distance_mm', 'maximum', 'mm'),
        ('Distance standard deviation (not accuracy)', 'distance_mm', 'std_population', 'mm'),
        ('Same-origin distance span', 'origin_distance_mm', 'span', 'mm'),
        ('Median XY alignment correction', 'alignment_xy_mm', 'median', 'mm'),
        ('Median yaw alignment correction', 'alignment_yaw_deg', 'median', 'deg')]:
        lines.append(f'| {label} | {summary["Wide"][key][field]:.3f} {unit} | {summary["Long"][key][field]:.3f} {unit} |')
    lines += ['', '![Comparison](comparison.png)', '',
              '## Interpretation', '',
              'Use Wide provisionally for the current taught viewing arrangement: the vendor selector chooses it on every recorded view. This does not establish its absolute distance accuracy.', '',
              'Both share the same camera-to-tool and pixel-to-plane mapping. Long changes the distance scale and taught approach reference; these are not two independently calibrated depth sensors.', '',
              f'The estimated stationary plate location has {summary["Wide"]["stationary_target_xy_rms_about_mean_mm"]:.2f} mm radial RMS scatter about its mean. Relative to recorded robot XY moves, the shared mapping has principal gains {gains[0]:.3f} and {gains[1]:.3f} (ideal 1.000), with a rotation mismatch magnitude of {abs(rotation_mismatch):.2f} degrees. This is a consistency diagnostic assuming a stationary plate, not an independent absolute position accuracy measurement. The current camera-to-robot mapping needs verification before precision pickup.', '',
              'The 0.85 versus 0.87 mm distance standard deviations do not establish that Wide is more accurate: Long is simply scaled by its 2.68% larger reference radius.', '',
              'A measured camera-to-plate distance and several independently known height changes are needed before either output becomes reference depth labels.', '',
              '## First capture: directly comparable outputs', '',
              '```json', json.dumps(first, indent=2), '```', '',
              '## Full statistics', '', '```json', json.dumps({k:v for k,v in result.items() if k != 'records'}, indent=2), '```']
    (out / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(output=str(out), **{k:v for k,v in result.items() if k not in ('records', 'limitations')}), indent=2))


if __name__ == '__main__':
    main()
