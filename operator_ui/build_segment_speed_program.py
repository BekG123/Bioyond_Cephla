"""Offline 220109 candidate: preserve all existing calibration/grip/E2 modules."""
import copy
import hashlib
import io
import json
from pathlib import Path
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
SOURCE=ROOT/'controller/main_hostpoint_descent_grip_e2_137.bin'
OUTPUT=ROOT/'controller/main_hostpoint_descent_grip_e2_queue_220109.bin'

def candidate_lua(source=None):
    text=(source if source is not None else (HERE/'lua/mod_Trajectory.lua').read_text(encoding='utf-8')).replace('\r','')
    def change(old,new,count=1):
        nonlocal text
        if text.count(old)!=count:raise ValueError('Unexpected trajectory baseline: '+old[:70])
        text=text.replace(old,new)
    change('local points, expected, token, speed, checksum, ready, consumed',
           'local points, expected, token, speed, checksum, ready, consumed, segment_speeds')
    change('ready, consumed = false, false','ready, consumed, segment_speeds = false, false, false')
    change('220108','220109',2)
    change('if op == 1 then','if op == 1 or op == 8 then -- 8 adds authenticated per-segment speeds')
    change('        TrajectoryInit()','        TrajectoryInit()\n        segment_speeds = op == 8')
    change('if op == 2 then','if op == 2 or op == 9 then\n        if (op == 9) ~= segment_speeds then reply(false); return end\n        local width = segment_speeds and 5 or 4')
    change('for j=1,4 do\n                local x = GetSysParamF((i-1)*4+j-1)',
           'for j=1,width do\n                local x = GetSysParamF((i-1)*width+j-1)')
    change('if not finite(x) then reply(false); return end',
           'if not finite(x) or (j==5 and (x<=0 or x>speed or x>137)) then reply(false); return end')
    change('for j=1,4 do checksum=addhash(checksum,batch[i][j]) end',
           'for j=1,width do checksum=addhash(checksum,batch[i][j]) end')
    change('),speed,-1,T0,U0)', '),segment_speeds and v[5] or speed,-1,T0,U0)')
    return text

def build(source=SOURCE,output=OUTPUT):
    source,output=Path(source),Path(output)
    if source.resolve()==output.resolve():raise ValueError('Never overwrite the published baseline')
    raw=source.read_bytes()
    if raw[:7]!=b'byrobot':raise ValueError('Unexpected Bioyond header')
    with zipfile.ZipFile(source) as z:
        metadata={i.filename:copy.copy(i) for i in z.infolist()}
        entries={n:z.read(n) for n in metadata}
    required=('main/mod_Descent.lua','main/mod_HostPoint.lua','main/mod_Trajectory.lua')
    if any(n not in entries for n in required) or b'250101' not in entries['main/mod_HostPoint.lua']:
        raise ValueError('Expected complete published descent/grip/E2 baseline')
    original=entries.copy()
    entries['main/mod_Trajectory.lua']=candidate_lua(entries['main/mod_Trajectory.lua'].decode('utf-8')).encode('utf-8')
    payload=io.BytesIO()
    with zipfile.ZipFile(payload,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():
            info=copy.copy(metadata[name]);attributes=info.external_attr
            z.writestr(info,data);info.external_attr=attributes
    output.write_bytes(b'byrobot'+payload.getvalue())
    digest=lambda data:hashlib.sha256(data).hexdigest()
    manifest=dict(protocol=220109,max_speed_mm_s=137,segment_speed_support=True,
        forward_speeds=[137,137,137,5],reverse_speeds=[5,137,137,137],
        completion_barriers_per_direction=1,zone=-1,source=source.name,
        source_sha256=digest(raw),output=output.name,output_sha256=digest(output.read_bytes()),
        changed=[n for n in entries if entries[n]!=original[n]],
        preserved=[n for n in entries if entries[n]==original[n]],hardware_tested=False,
        deployment='Unpublished candidate. Publish in Bioyond Works and verify 220109 before a supervised trial. Startup requires empty jaws; never restart onto a held plate.')
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest

if __name__=='__main__':
    result=build()
    (HERE/'lua/mod_Trajectory_segment_speeds.lua').write_text(candidate_lua(),encoding='utf-8')
    print(json.dumps(result,indent=2))
