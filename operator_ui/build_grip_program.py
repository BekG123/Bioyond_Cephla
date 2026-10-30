"""Merge gripper-only force control into the accepted descent/137 package."""
import copy
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent.parent
CONTROLLER_DIR=ROOT/'controller'


def build(source=CONTROLLER_DIR/'main_hostpoint_descent_137.bin',
          output=CONTROLLER_DIR/'main_hostpoint_descent_grip_137.bin'):
    source,output=Path(source),Path(output)
    if source.resolve()==output.resolve():raise ValueError('Preserve the descent baseline.')
    raw=source.read_bytes()
    if raw[:raw.index(b'PK\x03\x04')]!=b'byrobot':raise ValueError('Wrong archive header.')
    with zipfile.ZipFile(source) as z:
        entries={n:z.read(n) for n in z.namelist()}
        meta={i.filename:copy.copy(i) for i in z.infolist()}
    old=entries.copy()
    if b'230101' not in entries['main/mod_Descent.lua'] or b'220108' not in entries['main/mod_Trajectory.lua']:
        raise ValueError('Expected accepted descent and speed-137 baseline.')
    def change(name,before,after):
        s=entries[name].decode('utf-8').replace('\r','')
        if s.count(before)!=1:raise ValueError('Unexpected layout: '+name)
        entries[name]=s.replace(before,after).encode('utf-8')
    change('main/__loader.lua',' require("mod_Descent")',' require("mod_Descent")\n require("mod_Grip")')
    change('main/mod_Init.lua','    DescentInit()','    DescentInit()\n    GripInit()')
    change('main/mod_Socket.lua','    if(SYSINVAR0 == 23',
           '    if(SYSINVAR0 == 24 and SYSINVAR1 == 1) then\n        mod_Grip()\n    end\n    if(SYSINVAR0 == 23')
    # Retire the malformed legacy force branch instead of leaving a second,
    # unvalidated path that passes JointTarget/scalar to an ARRAY API.
    change('main/mod_HostPoint.lua',
           '        MoveExtJWithForce(JointTarget(0,0,0,0,0,0,LVAR7,LVAR_E2,0,0,0,0),LVAR5,LVAR6)\n        MOVFINISH()\n        mod_HostPointReport()',
           '        GotoError("Use the versioned Device 24 grip interface")\n        return')
    entries['main/mod_Grip.lua']=(ROOT/'operator_ui/lua/mod_Grip.lua').read_bytes()
    payload=io.BytesIO()
    with zipfile.ZipFile(payload,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():
            info=copy.copy(meta.get(name,meta['main/mod_HostPoint.lua']));info.filename=name
            attributes=info.external_attr;z.writestr(info,data);info.external_attr=attributes
    output.write_bytes(b'byrobot'+payload.getvalue())
    digest=lambda b:hashlib.sha256(b).hexdigest()
    result=dict(protocol=240101,source=source.name,source_sha256=digest(raw),
        output=output.name,output_sha256=digest(output.read_bytes()),
        changed=[n for n in entries if old.get(n)!=entries[n]],
        descent_unchanged=entries['main/mod_Descent.lua']==old['main/mod_Descent.lua'],
        trajectory_unchanged=entries['main/mod_Trajectory.lua']==old['main/mod_Trajectory.lua'],
        vendor_primitive_unchanged=entries['main/__lif.lua']==old['main/__lif.lua'],
        hardware_tested=False,force_profile_required=True,
        deployment='Configure reviewed torque profile, publish this package, then reload backend. No automatic deployment or motion.')
    output.with_suffix('.manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':print(json.dumps(build(),indent=2))
