"""Build an unpublished descent candidate, preserving the speed-137 baseline."""
import copy
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def build(source=ROOT/'main_hostpoint_trajectory_137.bin',
          output=ROOT/'main_hostpoint_descent_137.bin'):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError('Never overwrite the baseline program.')
    raw = source.read_bytes()
    prefix = raw[:raw.index(b'PK\x03\x04')]
    if prefix != b'byrobot':
        raise ValueError('Unexpected Bioyond archive header.')
    with zipfile.ZipFile(source) as archive:
        entries = {n: archive.read(n) for n in archive.namelist()}
        metadata = {i.filename: copy.copy(i) for i in archive.infolist()}
    old = entries.copy()
    if b'220108' not in entries['main/mod_Trajectory.lua']:
        raise ValueError('Expected the speed-137 trajectory baseline.')
    def change(name, before, after):
        text = entries[name].decode('utf-8').replace('\r', '')
        if text.count(before) != 1:
            raise ValueError(f'Unexpected layout: {name}')
        entries[name] = text.replace(before, after).encode('utf-8')
    change('main/__loader.lua', ' require("mod_Trajectory")',
           ' require("mod_Trajectory")\n require("mod_Descent")')
    change('main/mod_Init.lua', '    TrajectoryInit()',
           '    TrajectoryInit()\n    DescentInit()')
    change('main/mod_Socket.lua', '    if(SYSINVAR0 == 22',
           '    if(SYSINVAR0 == 23 and SYSINVAR1 == 1) then\n        mod_Descent()\n    end\n    if(SYSINVAR0 == 22')
    entries['main/mod_Descent.lua'] = (ROOT/'operator_ui/lua/mod_Descent.lua').read_bytes()
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            info = copy.copy(metadata.get(name, metadata['main/mod_HostPoint.lua']))
            info.filename = name
            attributes = info.external_attr
            archive.writestr(info, data)
            info.external_attr = attributes
    output.write_bytes(prefix + payload.getvalue())
    digest = lambda b: hashlib.sha256(b).hexdigest()
    manifest = dict(protocol=230101, trajectory_protocol=220108,
        source=source.name, source_sha256=digest(raw), output=output.name,
        output_sha256=digest(output.read_bytes()),
        changed=[n for n in entries if old.get(n) != entries[n]],
        preserved=[n for n in old if old[n] == entries[n]],
        approach_speed_mm_s=137, probe_speed_mm_s=5, slow_zone_mm=20,
        torque_check='Between completed 1/0.5 mm probe steps; not a force servo.',
        hardware_tested=False, deployment='Publish candidate in Bioyond Works; backend reload also required.')
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    print(json.dumps(build(), indent=2))
