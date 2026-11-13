"""Verify a portable run's event schema and artifact hashes. Never contacts hardware.

    py -m labfacade.verify_dataset path/to/run
"""
import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .artifacts import digest, inventory, relative_child, validate_ome


def verify_dataset(folder):
    folder = Path(folder).resolve()
    errors, checked = [], set()
    schema = json.loads((Path(__file__).parent / 'schemas/event.schema.json').read_text())
    validator = Draft202012Validator(schema)
    previous = 0
    run_id = json.loads((folder / 'run.json').read_text())['run_id']
    events = (folder / 'events.jsonl').read_text().splitlines()
    for number, line in enumerate(events, 1):
        try:
            event = json.loads(line)
            validator.validate(event)
            if event['run'] != run_id or event['seq'] <= previous:
                raise ValueError('Run ID mismatch or non-increasing sequence.')
            previous = event['seq']
            for artifact in event['artifacts']:
                key = (artifact['path'], artifact['sha256'])
                if key in checked:
                    continue
                path = relative_child(folder, artifact['path'])
                if digest(path) != artifact['sha256']:
                    raise ValueError(f'Hash mismatch: {artifact["path"]}')
                if path.name == 'files.manifest.json':
                    manifest = json.loads(path.read_text())
                    root = relative_child(path.parent, manifest['root'])
                    if inventory(root) != manifest['files']:
                        raise ValueError(f'Directory contents changed: {root}')
                    if manifest.get('format') == 'OME-Zarr':
                        validate_ome(root)
                checked.add(key)
        except Exception as error:
            errors.append(dict(line=number, error=str(error)))
    index = json.loads((folder / 'artifacts.json').read_text()) if (folder / 'artifacts.json').exists() else {'artifacts': []}
    for entry in index['artifacts']:
        if (entry['path'], entry['sha256']) not in checked:
            errors.append(dict(error='Indexed artifact has no verified event reference', path=entry['path']))
    return dict(ok=not errors, run_id=run_id, event_count=len(events), artifacts_verified=len(checked), errors=errors,
                scope='file integrity and supported OME metadata profile; not hardware or biological validation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    args = parser.parse_args()
    report = verify_dataset(args.run)
    print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
