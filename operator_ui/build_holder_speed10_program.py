"""Prepare a versioned holder speed trial; retain the proven speed-1 interface."""
import argparse
import copy
import hashlib
import io
import json
import zipfile
from build_holder_rotation_program import ROOT, BRANCH

SOURCE=ROOT/'controller/main_hostpoint_e2_holder_queue_220109.bin'

def build(speed=10):
    if speed not in (10,137):
        raise ValueError('Only the explicit speed-10 or speed-137 candidates are supported')
    output=ROOT/f'controller/main_hostpoint_e2_holder_speed{speed}_queue_220109.bin'
    protocol,probe,move=(250103,11,12) if speed==10 else (250104,13,14)
    with zipfile.ZipFile(SOURCE) as archive:
        metadata={i.filename:copy.copy(i) for i in archive.infolist()}
        original={n:archive.read(n) for n in metadata}
    entries=original.copy()
    name='main/mod_HostPoint.lua'
    code=entries[name].decode().replace('\r','')
    marker='    elseif (SYSINVAR4 == 6) then\n'
    if code.count(marker)!=1 or BRANCH not in code or 'SYSINVAR4 == 12' in code:
        raise ValueError('Unexpected holder source package')
    fast=(BRANCH.replace('SYSINVAR4 == 9',f'SYSINVAR4 == {probe}')
        .replace('SYSINVAR4 == 10',f'SYSINVAR4 == {move}')
        .replace('250102',str(protocol)).replace('MoveExtJ(LJ,1,',f'MoveExtJ(LJ,{speed},')
        .replace('Slow commissioning.',f'Fixed speed-{speed} supervised trial.'))
    entries[name]=code.replace(marker,fast+marker).encode()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for key,value in entries.items():archive.writestr(metadata[key],value)
    output.write_bytes(b'byrobot'+buffer.getvalue())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())==set(original)
        assert [n for n in original if original[n]!=archive.read(n)]==[name]
        assert BRANCH in archive.read(name).decode()
        assert fast in archive.read(name).decode()
    manifest=dict(source=SOURCE.name,output=output.name,
        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        changed=[name],protocol=protocol,probe_mode=probe,move_mode=move,speed_setting=speed,
        original_speed1_interface_preserved=True,trajectory_220109_unchanged=True,
        hardware_tested=False,speed_unit='Vendor MoveExtJ setting; not asserted to be degrees per second',
        requirements='Arm Home, empty jaws, retained plate, clear supervised sweep; verify capability and start position; no retry on uncertain outcome.')
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--speed',type=int,choices=(10,137),default=10)
    build(parser.parse_args().speed)
