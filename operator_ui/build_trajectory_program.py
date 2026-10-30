"""Build a Bioyond candidate project without connecting to the controller."""
import hashlib
import copy
import io
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONTROLLER_DIR = ROOT/'controller'


def build(source=CONTROLLER_DIR/'main_hostpoint_trq.bin',
          output=CONTROLLER_DIR/'main_hostpoint_trajectory_137.bin'):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError('Never overwrite the baseline program.')
    raw = source.read_bytes()
    prefix = raw[:raw.index(b'PK\x03\x04')]
    if not prefix.startswith(b'byrobot'):
        raise ValueError('Unexpected Bioyond archive header.')
    with zipfile.ZipFile(source) as z:
        entries = {n:z.read(n) for n in z.namelist()}
        metadata = {i.filename:copy.copy(i) for i in z.infolist()}
    old = entries.copy()
    def change(name, find, replacement):
        text = entries[name].decode('utf-8').replace('\r','')
        if text.count(find) != 1:
            raise ValueError(f'Unexpected baseline layout in {name}')
        entries[name] = text.replace(find,replacement).encode('utf-8')
    change('main/__loader.lua',' require("mod_HostPoint")',
           ' require("mod_HostPoint")\n require("mod_Trajectory")')
    change('main/mod_Init.lua','    SetLuaAppSta(1)',
           '    TrajectoryInit()\n    SetLuaAppSta(1)')
    change('main/mod_Socket.lua','    if(SYSINVAR0 == 21',
           '    if(SYSINVAR0 == 22 and SYSINVAR1 == 1) then\n        mod_Trajectory()\n    end\n    if(SYSINVAR0 == 21')
    entries['main/mod_Trajectory.lua'] = (HERE/'lua/mod_Trajectory.lua').read_bytes()
    # Bioyond strips its seven-byte header before unzipping. ZIP offsets must
    # therefore be relative to the ZIP payload, not to the prefixed .bin file.
    # Python tolerates both layouts; the vendor importer does not.
    payload = io.BytesIO()
    with zipfile.ZipFile(payload,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            info = copy.copy(metadata.get(name,metadata['main/mod_HostPoint.lua']))
            info.filename = name
            attributes = info.external_attr
            z.writestr(info,data)
            # zipfile substitutes Unix 0600 for zero attributes while writing.
            # Restore the vendor value before the central directory is emitted.
            info.external_attr = attributes
    output.write_bytes(prefix + payload.getvalue())
    digest = lambda data:hashlib.sha256(data).hexdigest()
    manifest = dict(protocol=220108,max_speed_mm_s=137,source=source.name,source_sha256=digest(raw),
        output=output.name,output_sha256=digest(output.read_bytes()),
        changed=[n for n in entries if entries[n]!=old.get(n)],
        preserved=[n for n in old if old[n]==entries[n]],
        deployment='Candidate only; publish in Bioyond Works, stop/start, verify version before execution.',
        zone=-1,hardware_tested=False)
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest


if __name__ == '__main__':
    print(json.dumps(build(),indent=2))
