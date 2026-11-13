"""Machine manifests: load, validate and answer questions about them.

Everything here fails closed. A manifest that does not validate is still
loaded, so describe() can say why, but every operation on it is refused.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re

import yaml
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[1]
MACHINES = REPO / 'machines'
RUNNABLE = ('qualified', 'supervised_only')


@dataclass(frozen=True)
class Refusal:
    """A structured 'no'. Never an exception: the agent reads it and reports it."""
    code: str
    reason: str
    detail: dict = field(default_factory=dict)


class Manifest:
    def __init__(self, path, data, sha256, errors):
        self.path = Path(path)
        self.data = data if isinstance(data, dict) else {}
        self.sha256 = sha256
        self.errors = list(errors)
        self.id = self.data.get('id') or self.path.stem

    @property
    def valid(self):
        return not self.errors

    def operations(self):
        ops = self.data.get('operations')
        return [op for op in ops if isinstance(op, dict) and op.get('name')] if isinstance(ops, list) else []

    def operation(self, name):
        return next((op for op in self.operations() if op['name'] == name), None)

    def qualification(self, op):
        """(status, entry). Reads need none. A motion with no entry is untested."""
        if op.get('risk') == 'read_only':
            return 'not_required', {}
        entries = self.data.get('qualification')
        entry = entries.get(op['name']) if isinstance(entries, dict) else None
        if not isinstance(entry, dict) or 'status' not in entry:
            return 'untested', {'blocker': f"No qualification entry named '{op['name']}' in {self.path.name}."}
        return entry['status'], entry

    def check_params(self, op, params):
        """Refuse a parameter the manifest does not declare, or one outside a limit of the same name."""
        declared = op.get('parameters') or {}
        limits = self.data.get('limits') if isinstance(self.data.get('limits'), dict) else {}
        for name, value in (params or {}).items():
            if name not in declared:
                return Refusal('undeclared_parameter',
                               f"'{name}' is not a declared parameter of {op['name']}.",
                               {'parameter': name, 'declared': sorted(declared)})
            limit = limits.get(name)
            if limit is None:
                continue
            bound = limit.get('value') if isinstance(limit, dict) else None
            number = type(value) in (int, float) and math.isfinite(value)
            if _is_number(bound):          # a single number is a maximum magnitude
                ok = number and abs(value) <= bound
            elif isinstance(bound, list) and len(bound) == 2 and all(_is_number(b) for b in bound):
                ok = number and bound[0] <= value <= bound[1]
            else:
                return Refusal('limit_not_checkable',
                               f"Limit '{name}' has a value this layer cannot check.",
                               {'parameter': name, 'limit': bound})
            if not ok:
                return Refusal('outside_limit', f"{name}={value!r} is outside the limit {bound!r}.",
                               {'parameter': name, 'value': value, 'limit': bound,
                                'units': limit.get('units'), 'source': limit.get('source')})
        return None

    def faults_affecting(self, name):
        faults = self.data.get('known_faults')
        return [f for f in faults if isinstance(f, dict) and name in (f.get('affects') or [])] \
            if isinstance(faults, list) else []


def _is_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def load_manifests(folder=MACHINES, schema_path=None):
    """{machine id: Manifest} for every *.yaml in the folder."""
    folder = Path(folder)
    schema_path = Path(schema_path or folder / 'manifest.schema.json')
    try:
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        validator, schema_error = Draft202012Validator(schema), None
    except Exception as error:
        validator, schema_error = None, f'schema unavailable: {error}'
    manifests = {}
    for path in sorted(folder.glob('*.yaml')):
        raw = path.read_bytes()
        errors = [schema_error] if schema_error else []
        try:
            data = yaml.safe_load(raw.decode('utf-8'))
        except Exception as error:
            data, errors = {}, errors + [f'not readable YAML: {error}']
        if not isinstance(data, dict):
            data, errors = {}, errors + ['top level is not a mapping']
        elif validator:
            errors += [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                       for e in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))]
            names = [op.get('name') for op in data.get('operations', []) if isinstance(op, dict)]
            if len(names) != len(set(names)):
                errors.append('operations: duplicate names')
        manifest = Manifest(path, data, hashlib.sha256(raw).hexdigest(), errors)
        if manifest.id in manifests:
            manifest.errors.append(f"duplicate machine id '{manifest.id}'")
            manifests[manifest.id].errors.append(f"duplicate machine id '{manifest.id}'")
            continue
        manifests[manifest.id] = manifest
    return manifests


def implemented_paths(text):
    """Repo-relative paths named in an implemented_by string."""
    paths = []
    for token in re.split(r'[\s,;()]+', text or ''):
        token = token.strip('\'"').rstrip('.:')
        if '/' in token and not token.startswith(('http', '--')):
            paths.append(token)
    return paths


def missing_implementations(manifest, repo=REPO):
    """[(operation, path)] for implemented_by paths that are not in the repo (drift check)."""
    return [(op['name'], path) for op in manifest.operations()
            for path in implemented_paths(op.get('implemented_by'))
            if not (Path(repo) / path).exists()]
