"""Build an unpublished E2 correction extension; preserve the existing package."""
import copy
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'controller/main_hostpoint_descent_grip_137.bin'
OUTPUT = ROOT / 'controller/main_hostpoint_descent_grip_e2_137.bin'
BRANCH = '''    elseif (SYSINVAR4 == 7) then
        -- Read-only capability probe; nonce prevents stale capability acceptance.
        SetSysInVarI(7,GetSysParamF(7))
        SetSysInVarI(8,250101)
    elseif (SYSINVAR4 == 8) then
        if GetSysInVarI(7) ~= GetSysParamF(7) or GetSysInVarI(8) ~= 250101 then
            GotoError("E2 capability handshake required")
            return
        end
        SetSysInVarI(7,0)
        SetSysInVarI(8,0)
        if LVAR_E2 ~= LVAR_E2 or math.abs(LVAR_E2-1.77)>2 then
            GotoError("E2 correction exceeds reviewed bound")
            return
        end
        -- Preserve E1 and every other external axis; fixed target and slow speed.
        MoveExtJ(JointTarget(0,0,0,0,0,0,LVAR_E1,1.77,GetElem(LJ,9),GetElem(LJ,10),GetElem(LJ,11),GetElem(LJ,12)),1,-1,T0,U0)
        MOVFINISH()
'''


def build(source=SOURCE, output=OUTPUT):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError('Preserve the source package')
    with zipfile.ZipFile(source) as archive:
        metadata = {i.filename: copy.copy(i) for i in archive.infolist()}
        entries = {n: archive.read(n) for n in metadata}
    original = entries.copy()
    name = 'main/mod_HostPoint.lua'
    text = entries[name].decode().replace('\r', '')
    marker = '    elseif (SYSINVAR4 == 6) then\n'
    if text.count(marker) != 1:
        raise ValueError('Unexpected host-point layout')
    # Use the vendor-supported SYSINVAR globals, as in the original program.
    entries[name] = text.replace(marker, BRANCH.replace('GetSysInVarI(7)', 'SYSINVAR7').replace('GetSysInVarI(8)', 'SYSINVAR8') + marker).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(metadata[name], data)
    output.write_bytes(b'byrobot' + buffer.getvalue())
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    manifest = dict(protocol=250101, source=source.name, source_sha256=digest(source),
                    output=output.name, output_sha256=digest(output),
                    changed=[n for n in entries if entries[n] != original[n]],
                    target_degrees=1.77, accepted_degrees=[1.77, 1.82],
                    max_correction_degrees=2, speed=1, hardware_tested=False,
                    deployment='Candidate only: publish through Bioyond Works, then stop/start with empty claws and verify.')
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    print(json.dumps(build(), indent=2))
