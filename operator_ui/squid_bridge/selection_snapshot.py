"""Recover only missing XY locations; all acquisition controls remain live."""
from copy import deepcopy
import hashlib
import math
import yaml


def layout_key(text):
    """Identify an XY layout independently of time, channels, focus or process ID."""
    import json
    data = yaml.safe_load(text)
    kind = data['acquisition']['widget_type']
    section, rows = ('wellplate_scan', 'regions') if kind == 'wellplate' else ('flexible_scan', 'positions')
    identity = dict(widget_type=kind, xy_mode=data['acquisition'].get('xy_mode'),
                    objective=data.get('objective'), sample=data.get('sample'), plate=data.get('plate'),
                    geometry={k:v for k,v in data[section].items() if k != rows})
    return hashlib.sha256(json.dumps(identity,sort_keys=True,allow_nan=False).encode()).hexdigest()


def recover_xy(current, previous_yaml):
    text = current['yaml']
    if hashlib.sha256(text.encode()).hexdigest() != current.get('sha256'):
        raise ValueError('Squid live controls checksum did not match.')
    live = yaml.safe_load(text)
    old = yaml.safe_load(previous_yaml)
    kind = live['acquisition']['widget_type']
    if kind not in ('wellplate', 'flexible'):
        raise ValueError('Select a supported acquisition tab in Squid.')
    section, rows = ('wellplate_scan', 'regions') if kind == 'wellplate' else ('flexible_scan', 'positions')
    if any(r.get('fovs') for r in live[section][rows]):
        return current  # A newly selected site takes precedence over history.
    # Locations are reusable only for the same tab, optics and XY layout.
    # Recovered locations are disclosed in a fresh plan; never a motion approval.
    if layout_key(text) != layout_key(previous_yaml):
        raise ValueError('Squid imaging tab, objective or XY layout changed. Select an imaging location for the current setup; no old settings were substituted.')
    recovered = deepcopy(old[section][rows])
    def xy(point):
        if len(point) not in (2, 3) or not all(type(v) in (int, float) and math.isfinite(v) for v in point):
            raise ValueError('Saved Squid imaging coordinates are invalid.')
        return point[:2]  # The current Z controls, not a historical focus, own Z.
    for row in recovered:
        row['center_mm'] = xy(row['center_mm'])
        row['fovs'] = [xy(p) for p in row['fovs']]
    fovs = sum(len(row['fovs']) for row in recovered)
    if not fovs:
        raise ValueError('No saved imaging locations are available.')
    live[section][rows] = recovered
    text = yaml.safe_dump(live, sort_keys=True)
    summary = dict(current['summary'], fovs=fovs)
    summary['total_images'] = fovs * len(summary['channels']) * summary['nz'] * summary['nt']
    return dict(yaml=text, sha256=hashlib.sha256(text.encode()).hexdigest(), summary=summary)
