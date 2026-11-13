"""Add opt-in, bounded Hamilton transit blending; legacy commands unchanged."""
import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'controller/main_hostpoint_mixed_wrist137_queue_220111.bin'
OUTPUT=ROOT/'controller/main_hostpoint_blended_transit_queue_220112.bin'


def candidate_lua(text):
    text=text.replace('\r','')
    def change(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Unexpected source: '+old)
        text=text.replace(old,new)
    change('segment_speeds, joint_pivot, mixed_wrist\n','segment_speeds, joint_pivot, mixed_wrist, blended_transit\n')
    change('ready, consumed, segment_speeds, joint_pivot, mixed_wrist = false, false, false, false, false',
           'ready, consumed, segment_speeds, joint_pivot, mixed_wrist, blended_transit = false, false, false, false, false, false')
    change('    if op == 13 then','''    if op == 15 then -- nonmoving optional bounded-transit capability
        for i=0,6 do SetSysInVarI(i,0) end
        SendSysOutVarI(1,220112)
        return
    end
    if op == 13 then''')
    change('if op == 1 or op == 8 or op == 10 or op == 12 then','if op == 1 or op == 8 or op == 10 or op == 12 or op == 16 then')
    change('        segment_speeds = op == 8 or op == 12','        segment_speeds = op == 8 or op == 12 or op == 16\n        blended_transit = op == 16')
    change('if op == 2 or op == 9 or op == 14 then','if op == 2 or op == 9 or op == 14 or op == 17 then')
    change('if (op == 14) ~= mixed_wrist or ((op == 9 or op == 14) ~= segment_speeds) then',
           'if (op == 17) ~= blended_transit or (op == 14) ~= mixed_wrist or ((op == 9 or op == 14 or op == 17) ~= segment_speeds) then')
    change('local width = mixed_wrist and 6 or (segment_speeds and 5 or 4)',
           'local width = (mixed_wrist or blended_transit) and 6 or (segment_speeds and 5 or 4)')
    change('(j==6 and x~=0 and x~=1)',
           '(j==6 and ((blended_transit and x~=-1 and x~=1) or (not blended_transit and x~=0 and x~=1)))')
    change('        if mixed_wrist then\n            local previous', '''        if blended_transit then
            -- Six-point forward route only. Blend the two level transit corners;
            -- never the lift, approach/descent transition, or final seating.
            if #points~=6 or speed~=137 then reply(false); return end
            for i=1,6 do
                local v=points[i]
                local zone=(i==2 or i==3) and 1 or -1
                if v[6]~=zone or v[5]~=(i==6 and 5 or 137) then reply(false); return end
                if zone==1 then
                    for j=i-1,i+1 do
                        if math.abs(points[j][3]-v[3])>0.006 then reply(false); return end
                    end
                    for j=i-1,i do
                        local a,b=points[j],points[j+1]
                        if (a[1]-b[1])^2+(a[2]-b[2])^2<16 then reply(false); return end
                    end
                end
            end
        end
        if mixed_wrist then
            local previous''')
    change('segment_speeds and v[5] or speed,-1,T0,U0)',
           'segment_speeds and v[5] or speed,blended_transit and v[6] or -1,T0,U0)')
    return text


def build(source=SOURCE,output=OUTPUT):
    with zipfile.ZipFile(source) as z:entries={i.filename:(copy.copy(i),z.read(i)) for i in z.infolist()}
    key='main/mod_Trajectory.lua';meta,raw=entries[key]
    entries[key]=(meta,candidate_lua(raw.decode('utf-8-sig')).encode())
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for meta,data in entries.values():z.writestr(meta,data)
    output.write_bytes(b'byrobot'+stream.getvalue())
    with zipfile.ZipFile(output) as z:
        if z.testzip():raise ValueError('Archive validation failed')
    d=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        changed=[key],base_protocol=220109,optional_blended_transit_capability=220112,
        legacy_capabilities_preserved=[220110,220111],segment_zones=[-1,1,1,-1,-1,-1],
        segment_speeds=[137,137,137,137,137,5],completion_barriers=1,publish_required=True,hardware_tested=False,
        source_documentation='Installed Bioyond BYCommand.json MoveL Chinese description: ZP is blend-region trajectory length; vendor MoveJump uses positive length zones.',
        limitation='Exact controller blend shape and physical velocity continuity require a supervised trial; no guarantee of speed137 through corners.')
    output.with_suffix('.manifest.json').write_text(json.dumps(d,indent=2),encoding='utf-8')
    return d


if __name__=='__main__':print(json.dumps(build(),indent=2))
