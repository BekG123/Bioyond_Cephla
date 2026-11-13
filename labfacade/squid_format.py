"""What image format is Squid configured to save? Reads files only.

The run dataset expects OME-Zarr 0.5 (FILE_SAVING_OPTION = ZARR_V3). Squid's
built-in default is individual images, and recent runs here wrote plain TIFF.
"""
from __future__ import annotations

from pathlib import Path
import re

WANTED = 'ZARR_V3'
_INI = re.compile(r'^\s*FILE_SAVING_OPTION\s*=\s*"?([A-Za-z_0-9]+)"?', re.M)
_DEFAULT = re.compile(r'^FILE_SAVING_OPTION\s*=\s*FileSavingOption\.([A-Z_0-9]+)', re.M)
_SIX_D = re.compile(r'^\s*ZARR_USE_6D_FOV_DIMENSION\s*=\s*"?(true|1)"?\s*$', re.M | re.I)


def configured_saving_format(software_dir, active_config=None):
    """{format, source, zarr, warning}. Which .ini Squid actually loads is not verified here."""
    software = Path(software_dir)
    found = {}
    six_d = []
    configs = [Path(active_config)] if active_config else sorted(software.glob('*.ini'))
    for path in configs:
        if not path.is_file():
            raise FileNotFoundError(f'Specified Squid configuration not found: {path}')
        text = path.read_text(encoding='utf-8', errors='replace')
        match = _INI.search(text)
        if match:
            found[path.name] = match.group(1).upper()
        if _SIX_D.search(text):
            six_d.append(path.name)
    if found:
        formats = sorted(set(found.values()))
        fmt, source = (formats[0] if len(formats) == 1 else 'CONFLICT'), found
    else:
        default = software / 'control' / '_def.py'
        match = _DEFAULT.search(default.read_text(encoding='utf-8', errors='replace')) if default.exists() else None
        fmt, source = (match.group(1) if match else 'UNKNOWN'), 'control/_def.py default'
    default = software / 'control' / '_def.py'
    default_text = default.read_text(encoding='utf-8', errors='replace') if default.exists() else ''
    # An explicit false overrides the default only in the explicitly selected INI.
    explicit_six = re.search(r'^\s*ZARR_USE_6D_FOV_DIMENSION\s*=\s*"?(true|false|1|0)"?\s*$',
                             configs[0].read_text() if active_config else '', re.M | re.I)
    if not explicit_six and _SIX_D.search(default_text):
        six_d.append('control/_def.py default')
    zarr = fmt == WANTED and not six_d
    warning = None
    if six_d:
        warning = f'6D FOV mode is on in {six_d}; that layout is not standard OME-Zarr.'
    elif fmt != WANTED:
        warning = f'Squid is set to save {fmt}, not OME-Zarr 0.5 ({WANTED}). Images will not land in plate.ome.zarr.'
    return dict(format=fmt, source=source, zarr=zarr, warning=warning,
                software_dir=str(software.resolve()), active_config=str(active_config) if active_config else None,
                runtime_verified=False, evidence='configuration files only; output validated separately')
