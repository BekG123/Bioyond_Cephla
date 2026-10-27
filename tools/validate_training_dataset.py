"""Validate an exported dataset without contacting instruments or changing sources."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re
import time

from build_training_dataset import parse, identifier


def rows(path):
    opener = gzip.open if path.name.endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            try:
                yield parse(line)
            except Exception as error:
                raise ValueError(f'{path.name}:{number}: {type(error).__name__}') from error


def validate(snapshot):
    info = json.loads((snapshot / 'dataset.json').read_text(encoding='utf-8'))
    counts, faults = {}, []
    root = Path(info['source_root'])
    manifests = {x['path']: x for x in rows(snapshot / 'source_manifest.jsonl')}
    groups = {x['group_id'] for x in rows(snapshot / 'splits/groups.jsonl')}
    observations = set()
    previous_samples, invalid_transition_ids = {}, set()
    mutable_assets = 0
    domain_counts, evidence_statuses = Counter(), Counter()
    paths = sorted(snapshot.rglob('*.jsonl')) + sorted(snapshot.rglob('*.jsonl.gz'))
    # Observation references must exist before the transitions are checked.
    paths.sort(key=lambda p: (0 if p.name == 'observations.jsonl.gz' else 1, str(p)))
    for path in paths:
        name = path.relative_to(snapshot).as_posix()
        count = 0
        for row in rows(path):
            count += 1
            if count % 1000000 == 0:
                print(json.dumps(dict(validating=name, records=count)), flush=True)
            if 'group_id' in row and row['group_id'] not in groups:
                faults.append(name + ': unknown group')
            source = row.get('source')
            if source and not source.endswith('memory.sqlite3') and source not in manifests:
                faults.append(name + ': missing source manifest')
            if name == 'motion/observations.jsonl.gz':
                if row['id'] in observations: faults.append(name + ': duplicate ID')
                observations.add(row['id'])
                if source.startswith('operator_ui/demonstrations/') and source.endswith('/samples.jsonl'):
                    previous = previous_samples.get(source)
                    if previous and previous['source_line'] + 1 != row['source_line']:
                        invalid_transition_ids.add(identifier(previous['id'] + ':' + row['id']))
                    previous_samples[source] = row
            elif name == 'motion/transitions.jsonl.gz':
                if row['observation_id'] not in observations or row['next_observation_id'] not in observations:
                    faults.append(name + ': missing observation')
                if row['id'] in invalid_transition_ids:
                    faults.append(name + ': transition crosses a missing/invalid source row: ' + row['id'])
                if not 0 < row['dt_s'] <= 1:
                    faults.append(name + ': invalid transition interval')
                if row['target_semantics'] != 'next_observed_state_not_command':
                    faults.append(name + ': ambiguous supervision')
            elif name == 'vision/assets.jsonl':
                if row.get('eligibility') == 'exclude_mutable_or_missing_source':
                    mutable_assets += 1
                elif not (root / source).is_file(): faults.append(name + ': missing asset')
                if row['sha256'] != manifests[source].get('sha256'):
                    faults.append(name + ': asset hash mismatch')
            elif name == 'labels/evidence.jsonl.gz':
                if row['eligibility'] != 'review_required': faults.append(name + ': unreviewed promotion')
                evidence_statuses[str(row['evidence'].get('status', row['evidence'].get('state', 'other')))] += 1
            if 'domain' in row: domain_counts[row['domain']] += 1
        counts[name] = count
        if count != info['counts'].get(name): faults.append(name + ': count mismatch')
        print(json.dumps(dict(validated=name, records=count)), flush=True)
    for name, expected in info['counts'].items():
        if name.endswith(('.jsonl', '.jsonl.gz')) and counts.get(name) != expected:
            faults.append(name + ': expected output missing')
    report = dict(ok=not faults, checked_at_unix=time.time(), record_counts=counts,
        source_files=len(manifests), changed_sources=sum(bool(x.get('changed_during_export')) for x in manifests.values()),
        mutable_or_missing_assets_excluded=mutable_assets,
        domain_record_counts=dict(domain_counts), evidence_status_counts=dict(evidence_statuses),
        issue_count=len(faults), issues=faults[:100], note='Structural validation only; not physical clearance, label approval, or model validation.')
    (snapshot / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(ok=report['ok'], source_files=report['source_files'], issues=report['issues'])), flush=True)
    if faults: raise SystemExit(1)


def remove_flagged_transitions(snapshot):
    """Losslessly retain passing rows from a full scan; archive exactly its flagged rows."""
    report_path=snapshot/'validation.json'
    report=parse(report_path.read_bytes())
    issues=report.get('issues',[])
    if report.get('ok') or not issues: raise ValueError('A failed full validation is required.')
    if report.get('issue_count',len(issues))!=len(issues) or len(issues)>=100:
        raise ValueError('A complete, non-truncated issue list is required.')
    bad=set()
    for issue in issues:
        match=re.fullmatch(r'motion/transitions.jsonl.gz: transition crosses a missing/invalid source row: ([a-f0-9]{24})',issue)
        if not match: raise ValueError('An unrelated validation issue requires separate review.')
        bad.add(match.group(1))
    info_path=snapshot/'dataset.json'; info=parse(info_path.read_bytes())
    name='motion/transitions.jsonl.gz'; path=snapshot/name; temp=path.with_suffix('.gz.tmp')
    excluded_path=snapshot/'quality/excluded_transitions.jsonl'
    if excluded_path.exists(): raise ValueError('Transition exclusions already exist; do not overwrite history.')
    found=[]; kept=0
    with gzip.open(path,'rt',encoding='utf-8') as source, gzip.open(temp,'wt',encoding='utf-8',compresslevel=1) as dest:
        for line in source:
            row=parse(line)
            if row['id'] in bad: found.append(row)
            else:
                dest.write(line); kept+=1
            if (kept+len(found)) % 1000000==0:
                print(json.dumps(dict(filtering_transitions=kept+len(found),excluded=len(found))),flush=True)
    if len(found)!=len(bad) or {x['id'] for x in found}!=bad:
        raise ValueError('Flagged IDs do not match the data exactly.')
    if kept+len(found)!=report['record_counts'][name] or kept+len(found)!=info['counts'][name]:
        raise ValueError('The dataset changed since full validation.')
    (snapshot/'validation_before_transition_cleanup.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    with excluded_path.open('w',encoding='utf-8') as stream:
        for row in found:
            stream.write(json.dumps(dict(id=row['id'],reason='crosses_missing_or_invalid_source_row',
                data=row,eligibility='excluded'),allow_nan=False)+'\n')
    temp.replace(path)
    excluded_name=excluded_path.relative_to(snapshot).as_posix()
    info['counts'][name]=kept
    info['counts'][excluded_name]=len(found)
    info['counts']['excluded_transition_source_gaps']=len(found)
    info['transition_cleanup_utc']=time.time()
    info_path.write_text(json.dumps(info,indent=2),encoding='utf-8')
    report['record_counts'][name]=kept
    report['record_counts'][excluded_name]=len(found)
    report.update(ok=True,issues=[],issue_count=0,resolved_issues=issues,checked_at_unix=time.time(),
        validation_method='Full structural scan, followed by lossless retention of unchanged passing rows and exclusion of exactly the flagged invalid transitions.')
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(ok=True,transitions_kept=kept,transitions_excluded=len(found))),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--remove-flagged-transitions',action='store_true')
    args=parser.parse_args()
    if args.remove_flagged_transitions: remove_flagged_transitions(args.snapshot)
    else: validate(args.snapshot)
