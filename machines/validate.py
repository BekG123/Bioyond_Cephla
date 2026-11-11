"""Validate every machines/*.yaml against manifest.schema.json.

Read-only. No hardware is contacted.
    py machines/validate.py
"""
import json
from pathlib import Path
import sys

import yaml
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent


def check(manifest, schema):
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
              for e in sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda e: list(e.absolute_path))]
    # Cross-checks the schema cannot express.
    names = [op['name'] for op in manifest.get('operations', [])]
    if len(names) != len(set(names)):
        errors.append('operations: duplicate names')
    frames = set(manifest.get('frames', {}))
    for loc in manifest.get('locations', []):
        if loc['frame'] not in frames:
            errors.append(f"locations/{loc['name']}: frame '{loc['frame']}' is not declared in frames")
    for fault in manifest.get('known_faults', []):
        for op in fault.get('affects', []):
            if op not in names:
                errors.append(f"known_faults/{fault['id']}: affects unknown operation '{op}'")
    return errors


def main():
    schema = json.loads((HERE / 'manifest.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    failed = False
    for path in sorted(HERE.glob('*.yaml')):
        manifest = yaml.safe_load(path.read_text(encoding='utf-8'))
        errors = check(manifest, schema)
        print(f"{path.name}: {'ok' if not errors else 'FAILED'}  ({len(manifest['operations'])} operations)")
        for error in errors:
            print('   ', error)
        failed |= bool(errors)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
