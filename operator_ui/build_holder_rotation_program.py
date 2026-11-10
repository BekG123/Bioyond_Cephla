"""Prepare an unpublished holder-only commissioning command; never run hardware."""
import copy
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'controller/main_hostpoint_descent_grip_e2_queue_220109.bin'
OUTPUT = ROOT / 'controller/main_hostpoint_e2_holder_queue_220109.bin'
BRANCH = '''    elseif (SYSINVAR4 == 9) then
        -- Non-motion probe for the holder commissioning interface.
        SetSysInVarI(7,GetSysParamF(7))
        SetSysInVarI(8,250102)
    elseif (SYSINVAR4 == 10) then
        -- Host must verify arm clearance and empty jaws before this command.
        local nonce = GetSysParamF(7)
        local expected = GetSysParamF(8)
        local target = GetSysParamF(9)
        if SYSINVAR7 ~= nonce or SYSINVAR8 ~= 250102 or nonce <= 0 then
            GotoError("Holder capability handshake required")
            return
        end
        SetSysInVarI(7,0)
        SetSysInVarI(8,0)
        if expected ~= expected or target ~= target or LVAR_E2 ~= LVAR_E2 then
            GotoError("Invalid holder position")
            return
        end
        if math.abs(LVAR_E2-expected)>0.1 or math.abs(target-expected)>90.01
            or math.abs(target)>360 or math.abs(expected)>360 then
            GotoError("Holder start or quarter-turn bound mismatch")
            return
        end
        -- Preserve all joints/external axes except the holder. Slow commissioning.
        SetElem(LJ,8,target)
        MoveExtJ(LJ,1,-1,T0,U0)
        MOVFINISH()
        local actual = GetElem(GetCJoints(),8)
        if actual ~= actual or math.abs(actual-target)>0.1 then
            GotoError("Holder arrival mismatch")
            return
        end
'''


def build():
    with zipfile.ZipFile(SOURCE) as archive:
        metadata = {i.filename: copy.copy(i) for i in archive.infolist()}
        original = {n: archive.read(n) for n in metadata}
    entries = original.copy()
    name = 'main/mod_HostPoint.lua'
    code = entries[name].decode().replace('\r', '')
    marker = '    elseif (SYSINVAR4 == 6) then\n'
    if code.count(marker) != 1 or 'SYSINVAR4 == 10' in code:
        raise ValueError('Unexpected source host interface')
    entries[name] = code.replace(marker, BRANCH + marker).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for key, value in entries.items():
            archive.writestr(metadata[key], value)
    OUTPUT.write_bytes(b'byrobot' + buffer.getvalue())
    with zipfile.ZipFile(OUTPUT) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(original)
        changed = [n for n in original if archive.read(n) != original[n]]
        assert changed == [name]
        assert archive.read('main/mod_Trajectory.lua') == original['main/mod_Trajectory.lua']
    manifest = dict(source=SOURCE.name, output=OUTPUT.name,
        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        output_sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        changed=changed, protocol=250102, probe_mode=9, move_mode=10,
        parameters={'7': 'nonce', '8': 'expected E2 degrees', '9': 'target E2 degrees'},
        speed=1, max_delta_degrees=90.01, hardware_tested=False,
        ccw_axis_sign_verified=False, pickup_validated=False,
        deployment='Unpublished. Establish CCW sign using a small supervised move before a quarter-turn. Do not run legacy calibration: it resets E2.',
        vendor_short_side=dict(open_e1_mm=28, close_e1_mm=22,
            note='Vendor defaults, not an accepted grip for the current 48-well plate.'))
    OUTPUT.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    print(json.dumps(build(), indent=2))
