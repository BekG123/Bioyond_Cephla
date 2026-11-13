"""Local, immutable evidence packaging. Never discovers or commands hardware."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
from uuid import uuid4

FOLDERS = {'bioyond_s4': 'bioyond', 'hamilton_prep': 'hamilton', 'squid': 'squid'}


def component(value):
    value = str(value)
    if not value or value in ('.', '..') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in value):
        raise ValueError(f'Unsafe dataset path component: {value!r}')
    return value


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def inventory(root):
    root = Path(root)
    if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
        raise ValueError('Linked artifact roots are not allowed.')
    result = []
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError(f'Linked artifact member: {p}')
        if not p.resolve().is_relative_to(root.resolve()):
            raise ValueError('Artifact escapes its root.')
        if p.is_file():
            result.append(dict(path=p.relative_to(root).as_posix(), size=p.stat().st_size, sha256=digest(p)))
    if not result:
        raise ValueError('Empty artifact directory.')
    return result


def relative_child(root, value):
    part = PurePosixPath(value)
    if not value or part.is_absolute() or '..' in part.parts or '\\' in value or ':' in value:
        raise ValueError(f'Invalid dataset member path: {value!r}')
    target = (root / value).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('Dataset member escapes root.')
    return target


def validate_ome(root):
    """Validate the supported OME-Zarr 0.5 image/HCS metadata profile.

    Checks hierarchy, axes, dimensionality and transforms, not codec decoding or
    scientific completeness. Sparse Zarr chunks are legal. Never converts TIFF.
    """
    root = Path(root)
    inventory(root)  # reject links before reading metadata
    if not (root / 'zarr.json').is_file():
        raise ValueError('OME-Zarr requires a Zarr v3 root.')
    images = 0
    for file in sorted(root.rglob('zarr.json')):
        meta = json.loads(file.read_text(encoding='utf-8'))
        if meta.get('zarr_format') != 3:
            raise ValueError(f'Not Zarr v3: {file}')
        if meta.get('node_type') not in ('array', 'group'):
            raise ValueError('Invalid Zarr node type.')
        attrs = meta.get('attributes', {})
        squid = attrs.get('_squid', {})
        if squid.get('acquisition_complete') is False:
            raise ValueError('Acquisition is not finalized.')
        if '6D' in str(squid.get('structure', '')):
            raise ValueError('Non-standard 6D FOV layout is not accepted.')
        if meta.get('node_type') == 'array':
            shape = meta.get('shape', [])
            if not 2 <= len(shape) <= 5:
                raise ValueError('OME image arrays must have 2 to 5 dimensions; 6D is not accepted.')
            if any(type(size) is not int or size <= 0 for size in shape):
                raise ValueError('Image shape must contain positive integers.')
            if not meta.get('data_type') or not meta.get('chunk_grid') or not meta.get('codecs'):
                raise ValueError('Missing Zarr array storage metadata.')
        ome = attrs.get('ome')
        if not ome:
            continue
        if ome.get('version') != '0.5':
            raise ValueError('OME metadata version must be 0.5.')
        if 'plate' in ome:
            plate = ome['plate']
            for well in plate.get('wells', []):
                child = relative_child(file.parent, well['path'])
                child_ome = json.loads((child / 'zarr.json').read_text(encoding='utf-8'))['attributes']['ome']
                if 'well' not in child_ome:
                    raise ValueError('Plate references a missing well.')
                if not (0 <= well['rowIndex'] < len(plate['rows']) and 0 <= well['columnIndex'] < len(plate['columns'])):
                    raise ValueError('Well index outside plate layout.')
        if 'well' in ome:
            for entry in ome['well'].get('images', []):
                child = relative_child(file.parent, entry['path'])
                child_ome = json.loads((child / 'zarr.json').read_text(encoding='utf-8'))['attributes']['ome']
                if not child_ome.get('multiscales'):
                    raise ValueError('Well references a missing image.')
        for scale in ome.get('multiscales', []):
            if meta.get('node_type') != 'group':
                raise ValueError('OME image metadata must be on a group, not an array.')
            axes = scale.get('axes', [])
            names = [a['name'] for a in axes]
            types = [a.get('type') for a in axes]
            if not 2 <= len(axes) <= 5 or len(set(names)) != len(names):
                raise ValueError('Invalid OME axes; 6D is not accepted.')
            if any(t not in ('time', 'channel', 'space') for t in types):
                raise ValueError('Unsupported OME axis type.')
            if types != sorted(types, key=('time', 'channel', 'space').index) or types.count('time') > 1 or types.count('channel') > 1 or types.count('space') not in (2, 3):
                raise ValueError('Invalid OME axis order or spatial dimensionality.')
            if not scale.get('datasets'):
                raise ValueError('Image has no resolution levels.')
            for level in scale['datasets']:
                array = json.loads((relative_child(file.parent, level['path']) / 'zarr.json').read_text(encoding='utf-8'))
                if array.get('node_type') != 'array' or array.get('dimension_names') != names or len(array.get('shape', [])) != len(names):
                    raise ValueError('Image array dimensions do not match OME axes.')
                transforms = level.get('coordinateTransformations', [])
                if [t.get('type') for t in transforms] not in (['scale'], ['scale', 'translation']):
                    raise ValueError('Each image level needs scale and optional translation.')
                for transform in transforms:
                    values = transform[transform['type']]
                    if len(values) != len(names) or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                        raise ValueError('Invalid OME coordinate transform.')
                    if transform['type'] == 'scale' and any(v <= 0 for v in values):
                        raise ValueError('OME scales must be positive.')
            images += 1
    if not images:
        raise ValueError('No OME-Zarr 0.5 images found.')
    return dict(format='OME-Zarr', version='0.5', image_count=images, validation='metadata-profile; chunks hashed, not decoded')


def package(run_root, machine, step, source, *, ome=False):
    """Unique per-copy location; directory artifacts point to a hashed file manifest."""
    source = Path(source)
    if source.is_symlink() or (hasattr(source, 'is_junction') and source.is_junction()):
        raise ValueError('Linked artifacts are not allowed.')
    source = source.resolve(strict=True)
    parent = Path(run_root) / component(FOLDERS.get(machine, machine)) / component(step or 'run') / uuid4().hex
    parent.mkdir(parents=True)
    target = parent / source.name
    detail = dict(original=str(source), type='directory' if source.is_dir() else 'file')
    if source.is_dir():
        if source.is_relative_to(Path(run_root).resolve()) or Path(run_root).resolve().is_relative_to(source):
            raise ValueError('Cannot recursively collect the run or its parents.')
        before = inventory(source)
        if ome:
            detail.update(validate_ome(source))
        shutil.copytree(source, target)
        after = inventory(target)
        if before != after or before != inventory(source):
            raise ValueError('Source changed during collection; snapshot is not verified.')
        detail['root'] = target.relative_to(run_root).as_posix()
        manifest = parent / 'files.manifest.json'
        manifest.write_text(json.dumps(dict(v=1, root=target.name, files=after, **{k:v for k,v in detail.items() if k != 'root'}), indent=2))
        artifact = dict(path=manifest.relative_to(run_root).as_posix(), sha256=digest(manifest))
    else:
        before = digest(source)
        shutil.copy2(source, target)
        if before != digest(target) or before != digest(source):
            raise ValueError('Source changed during collection; snapshot is not verified.')
        artifact = dict(path=target.relative_to(run_root).as_posix(), sha256=before)
    return artifact, detail


def write_array(path, array):
    """Small numeric payloads as uncompressed Zarr v3; not labelled OME imagery."""
    import numpy as np
    array = np.asarray(array)
    if array.dtype.kind not in 'biuf' or array.ndim == 0 or any(s == 0 for s in array.shape):
        raise ValueError('Only nonempty numeric arrays can be stored as Zarr.')
    array = np.ascontiguousarray(array.astype(array.dtype.newbyteorder('<'), copy=False))
    path = Path(path)
    path.mkdir(parents=True)
    dtype = 'bool' if array.dtype.kind == 'b' else array.dtype.name
    metadata = dict(zarr_format=3, node_type='array', shape=list(array.shape), data_type=dtype,
                    chunk_grid=dict(name='regular', configuration=dict(chunk_shape=list(array.shape))),
                    chunk_key_encoding=dict(name='default', configuration=dict(separator='/')),
                    fill_value=False if dtype == 'bool' else 0,
                    codecs=[dict(name='bytes', configuration=dict(endian='little'))], attributes={})
    (path / 'zarr.json').write_text(json.dumps(metadata))
    chunk = path / 'c'
    for _ in array.shape:
        chunk = chunk / '0'
    chunk.parent.mkdir(parents=True)
    chunk.write_bytes(array.tobytes(order='C'))


def externalize(value, root, machine, step):
    """NumPy arrays become Zarr artifacts; ordinary JSON lists remain factual data."""
    artifacts = []
    def walk(item):
        if type(item).__module__.split('.')[0] == 'numpy':
            if getattr(item, 'ndim', 0) == 0:
                return item.item()
            folder = Path(root) / component(FOLDERS.get(machine, machine or 'data')) / component(step or 'run') / uuid4().hex
            array_path = folder / 'array.zarr'
            write_array(array_path, item)
            manifest = folder / 'files.manifest.json'
            manifest.write_text(json.dumps(dict(v=1, root='array.zarr', format='Zarr', files=inventory(array_path))))
            artifact = dict(path=manifest.relative_to(root).as_posix(), sha256=digest(manifest))
            artifacts.append(artifact)
            return dict(array_artifact=artifact['path'], shape=list(item.shape), dtype=str(item.dtype))
        if isinstance(item, dict):
            return {key: walk(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [walk(val) for val in item]
        return item
    return walk(value), artifacts
