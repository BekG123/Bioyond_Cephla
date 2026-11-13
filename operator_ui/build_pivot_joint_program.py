"""Offline optional queued wrist capability; existing220109 commands unchanged."""
import copy
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'controller/main_hostpoint_e2_holder_speed137_queue_220109.bin'
OUTPUT=ROOT/'controller/main_hostpoint_e2_holder_pivot137_queue_220110.bin'

def candidate_lua(text):
    text=text.replace('\r','')
    def change(old,new,count=1):
        nonlocal text
        if text.count(old)!=count:raise ValueError('Unexpected published source: '+old)
        text=text.replace(old,new)
    change('local points, expected, token, speed, checksum, ready, consumed, segment_speeds',
           'local points, expected, token, speed, checksum, ready, consumed, segment_speeds, joint_pivot')
    change('ready, consumed, segment_speeds = false, false, false',
           'ready, consumed, segment_speeds, joint_pivot = false, false, false, false')
    change('    if op == 6 then', '''    if op == 11 then -- nonmoving optional wrist capability
        for i=0,6 do SetSysInVarI(i,0) end
        SendSysOutVarI(1,220110)
        return
    end
    if op == 6 then''')
    change('if op == 1 or op == 8 then','if op == 1 or op == 8 or op == 10 then')
    change('        segment_speeds = op == 8','        segment_speeds = op == 8\n        joint_pivot = op == 10')
    change('        token = incoming','''        if joint_pivot and (expected~=1 or speed~=137) then reply(false); return end
        token = incoming''')
    change('        ready = true', '''        if joint_pivot then
            for i=1,3 do
                if math.abs(points[1][i]-points.start[i])>0.006 then reply(false); return end
            end
            if math.abs(points[1][4]-points.start[4])>180.001 then reply(false); return end
        end
        ready = true''')
    old='            MoveL(RobTarget(v[1],v[2],v[3],0,0,v[4],e[1],e[2],e[3],e[4],e[5],e[6]),segment_speeds and v[5] or speed,-1,T0,U0)'
    change(old,'''            local target = RobTarget(v[1],v[2],v[3],0,0,v[4],e[1],e[2],e[3],e[4],e[5],e[6])
            if joint_pivot then
                -- Only fixed-XYZ wrist turns, checked by host IK and Lua.
                MoveJ(target,137,-1,T0,U0)
            else
                MoveL(target,segment_speeds and v[5] or speed,-1,T0,U0)
            end''')
    return text

def build(source=SOURCE,output=OUTPUT):
    with zipfile.ZipFile(source) as z:
        meta={i.filename:copy.copy(i) for i in z.infolist()};old={n:z.read(n) for n in meta}
    entries=old.copy();key='main/mod_Trajectory.lua'
    entries[key]=candidate_lua(old[key].decode('utf-8-sig')).encode()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for n,data in entries.items():z.writestr(meta[n],data)
    output.write_bytes(b'byrobot'+buffer.getvalue())
    with zipfile.ZipFile(output) as z:assert z.testzip() is None
    manifest=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        output=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),changed=[key],
        base_protocol=220109,pivot_capability=220110,pivot_command='one MoveJ at137; one MOVFINISH',
        controller_speed_units='Vendor motion setting; not a measured angular velocity',
        hardware_tested=False,publish_required=True)
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2))
    return manifest

if __name__=='__main__':print(json.dumps(build(),indent=2))
