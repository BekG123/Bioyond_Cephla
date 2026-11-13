"""Offline timing analysis: saved images only, no API or hardware access."""
import argparse
import cProfile
import io
import json
import pstats
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'operator_ui/reports/plate48_timing_20261109'


def history():
    runs = {}
    sessions = ['20261108T061347Z_3d057999', '20261108T105724Z_14df5ed8']
    for session in sessions:
        for file in sorted((ROOT / 'operator_ui/logs/audit' / session).glob('*.jsonl')):
            for line in file.open(encoding='utf-8'):
                if '"sequence": "plate48_calibrate"' not in line:
                    continue
                if not any('"event": "' + event + '"' in line for event in
                           ['sequence_started', 'sequence_finished', 'sequence_progress',
                            'plate48_stationary_image_burst', 'plate48_observation',
                            'plate48_vision_rejected_stationary']):
                    continue
                row = json.loads(line)
                run = runs.setdefault(row['run_id'], {'session': session, 'events': []})
                m = row.get('measurement', {})
                run['events'].append(dict(time=row['timestamp'], event=row['event'],
                    error=row.get('error'), message=row.get('message', row.get('msg')),
                    result=row.get('result'), image=row.get('median_image'), pose=row.get('pose'),
                    wells=m.get('tracking', {}).get('supported_wells'),
                    initializer=m.get('tracking', {}).get('initialization'),
                    error_xy_mm=m.get('error_xy_mm')))
    for key, run in runs.items():
        burst = None
        durations = []
        for event in run['events']:
            if event['event'] == 'plate48_stationary_image_burst':
                burst = datetime.fromisoformat(event['time'])
            elif event['event'] == 'plate48_observation' and burst:
                durations.append((datetime.fromisoformat(event['time']) - burst).total_seconds())
                burst = None
        run['processing_seconds'] = durations
        print(json.dumps(dict(run=key, session=run['session'],
            observations=len(durations), processing_seconds=durations,
            final=run['events'][-1])), flush=True)
    (OUT / 'history.json').write_text(json.dumps(runs, indent=2), encoding='utf-8')


def benchmark():
    import cv2
    import numpy as np
    from projected_alignment import perception_at_height, target_from_mark
    from plate48_workflow import reference, match_placement
    records = json.loads((ROOT / 'operator_ui/reports/squid_48well_approach/'
        'calibration_squid_retry02_20261109/vision_events.json').read_text(encoding='utf-8-sig'))
    frames = [r for r in records if r['event'] == 'plate48_stationary_image_burst']
    images = [cv2.imread(r['median_image']) for r in frames]
    pose = frames[0]['pose']
    default = cv2.getNumThreads()
    result = dict(opencv=cv2.__version__, default_threads=default,
                  cpu_count=cv2.getNumberOfCPUs(), optimized=cv2.useOptimized(),
                  opencl=cv2.ocl.useOpenCL(), input_images=[r['median_image'] for r in frames], runs=[])
    t = time.perf_counter()
    base, _, _ = perception_at_height()
    result['reference_setup_seconds'] = time.perf_counter() - t
    print(json.dumps({k: v for k, v in result.items() if k != 'runs'}), flush=True)
    raw = reference(require_grip=False)[2]
    baseline = []
    for threads in [None, default, 1, 4, default]:
        if threads is not None:
            cv2.setNumThreads(threads)
        p = base
        p.tracker.previous_verified_seed = None
        p.last_measurement_pose = None
        run = dict(threads=threads, actual_threads=cv2.getNumThreads(), observations=[])
        for i in range(3):
            profiler = cProfile.Profile()
            start = time.perf_counter()
            profiler.enable()
            m = p.measure(images[i % len(images)], pose)
            profiler.disable()
            elapsed = time.perf_counter() - start
            target = target_from_mark(pose, m, p.cfg)
            try:
                match_placement(target, raw)
                placement = 'pass'
            except Exception as error:
                placement = str(error)
            observation = dict(index=i, seconds=elapsed, target=target, placement=placement,
                supported_wells=m['tracking']['supported_wells'],
                error_xy_mm=m['error_xy_mm'],
                disk_spread_px=m['tracking']['disk_group_spread_px'],
                initializer=m['tracking'].get('initialization'))
            if len(result['runs']) == 0:
                baseline.append(target)
            else:
                observation['target_delta_from_default'] = {k: target[k]-baseline[i][k] for k in target}
            run['observations'].append(observation)
            stream = io.StringIO()
            pstats.Stats(profiler, stream=stream).sort_stats('cumulative').print_stats(25)
            (OUT / f'profile_{len(result["runs"])}_threads{threads}_frame{i}.txt').write_text(stream.getvalue())
            print(json.dumps(dict(threads=threads, **observation)), flush=True)
        result['runs'].append(run)
        (OUT / 'benchmark.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    cv2.setNumThreads(default)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.history:
        history()
    elif args.worker:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(benchmark).result()
    else:
        benchmark()
