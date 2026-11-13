"""File-only receipt backfill for a stopped/completed plate workflow; never dispatches.

    py -m labfacade.reconcile_dataset RUN --checkout EXECUTION_CHECKOUT

Use with no other writer for this run. Original events, signed approval, ledger and
published artifacts are preserved. The prior completeness summary is archived.
"""
import argparse
from pathlib import Path
import json

from .dataset import bioyond_receipt_roots, collect_receipts, inspection_quality
from .events import RunFolder
from .verify_dataset import verify_dataset


COLLECTION_GAPS = {'evidence_not_collected', 'evidence_path_rejected', 'evidence_limit'}


def reconcile_dataset(folder, checkout, step='s01'):
    integrity = verify_dataset(folder)
    if not integrity['ok']:
        raise ValueError('Existing dataset failed integrity verification; no reconciliation written.')
    run = RunFolder(folder)
    plan_step = next((s for s in run.plan['steps'] if s['id'] == step), {})
    if plan_step.get('machine') != 'bioyond_s4' or plan_step.get('operation') != 'run_plate_workflow':
        raise ValueError('Only a bound Bioyond plate-workflow step can be recollected.')
    events = [e for e in run.events.read() if e['step'] == step]
    dispatches = [e['seq'] for e in events if e['kind'] == 'command' and e['status'] == 'sent']
    terminals = [e['seq'] for e in events if e['kind'] in ('result', 'pause')]
    if not dispatches or not terminals or max(terminals) <= max(dispatches):
        raise ValueError('Run must have a terminal result/pause after its last dispatch; stop its writer first.')
    # The wrapper reports its root receipt before motion; use that explicit identity.
    records = [e['data'].get('line', {}).get('record') for e in events
               if e['status'] == 'progress' and isinstance(e['data'].get('line'), dict)]
    source = next((Path(p).resolve() for p in records if p), None)
    index = run.read_json('artifacts.json')['artifacts']
    if source is None or not any(a.get('original') == str(source) and a.get('step') == step for a in index):
        raise ValueError('No previously hashed root workflow receipt; cannot bind historical collection.')
    roots = bioyond_receipt_roots(checkout)
    if not any(source.is_relative_to(p.resolve()) for p in roots):
        raise ValueError('Workflow receipt does not belong to the supplied checkout.')
    summary = run.read_json('dataset.json')
    if not summary or step not in summary.get('steps', {}):
        raise ValueError('No original collection summary.')
    previous = run.collect('bioyond_s4', run.path / 'dataset.json', step)
    start_seq = run.events.seq
    run.events.emit('status', machine='bioyond_s4', step=step, status='dataset_reconciliation_started',
                    data=dict(source=str(source), mode='files_only', hardware_commands_sent=False), artifacts=[previous])
    collected = collect_receipts(run, 'bioyond_s4', step, [source], roots, reuse_existing=True)
    for entry in index:
        if entry.get('step') != step or entry.get('type') != 'inspection_frame':
            continue
        quality = inspection_quality(run.path / entry['path'])
        artifact = {k: entry[k] for k in ('path', 'sha256')}
        run.events.emit('anomaly' if quality['status'] == 'suspect' else 'status', machine='bioyond_s4',
                        step=step, status='frame_quality_suspect' if quality['status'] == 'suspect' else 'frame_quality_reviewed',
                        data=dict(when=entry.get('when'), path=entry['path'], quality=quality, post_run=True), artifacts=[artifact])
    # Preserve unrelated old gaps. Collection gaps are replaced by this attempt's
    # results; every historical anomaly remains in the append-only event log.
    gaps = [g for g in summary['steps'][step]['gaps']
            if g['status'] not in COLLECTION_GAPS | {'frame_quality_suspect'}]
    gaps += [dict(status=e['status'], detail=e['data']) for e in run.events.read()
             if e['seq'] > start_seq and e['step'] == step and e['kind'] == 'anomaly']
    total = sum(a.get('step') == step for a in run.read_json('artifacts.json')['artifacts'])
    summary['steps'][step].update(artifact_count=total, complete=not gaps, gaps=gaps,
                                 reconciliation=dict(previous_summary=previous, mode='files_only'))
    run.write_json('dataset.json', summary)
    run.events.emit('status', machine='bioyond_s4', step=step, status='dataset_reconciled',
                    data=dict(artifact_count=total, receipt_count=len(collected), complete=not gaps,
                              gaps=gaps, historical_events_preserved=True), artifacts=[previous])
    return dict(verification=verify_dataset(folder), dataset=summary['steps'][step])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--checkout', required=True)
    parser.add_argument('--step', default='s01')
    args = parser.parse_args()
    report = reconcile_dataset(args.run, args.checkout, args.step)
    print(json.dumps(report, indent=2))
    return 0 if report['verification']['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
