"""Add opt-in mixed linear/fixed-position wrist queue; legacy commands unchanged."""
import copy,hashlib,io,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'controller/main_hostpoint_e2_holder_pivot137_queue_220110.bin'
OUTPUT=ROOT/'controller/main_hostpoint_mixed_wrist137_queue_220111.bin'

def candidate_lua(text):
    text=text.replace('\r','')
    def change(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Unexpected source: '+old)
        text=text.replace(old,new)
    change('segment_speeds, joint_pivot\n','segment_speeds, joint_pivot, mixed_wrist\n')
    change('ready, consumed, segment_speeds, joint_pivot = false, false, false, false',
           'ready, consumed, segment_speeds, joint_pivot, mixed_wrist = false, false, false, false, false')
    change('    if op == 11 then', '''    if op == 13 then -- optional mixed fixed-XYZ wrist queue
        for i=0,6 do SetSysInVarI(i,0) end
        SendSysOutVarI(1,220111)
        return
    end
    if op == 11 then''')
    change('if op == 1 or op == 8 or op == 10 then','if op == 1 or op == 8 or op == 10 or op == 12 then')
    change('        segment_speeds = op == 8','        segment_speeds = op == 8 or op == 12\n        mixed_wrist = op == 12')
    change('if op == 2 or op == 9 then','if op == 2 or op == 9 or op == 14 then')
    change('        if (op == 9) ~= segment_speeds then reply(false); return end',
           '        if (op == 14) ~= mixed_wrist or ((op == 9 or op == 14) ~= segment_speeds) then reply(false); return end')
    change('        local width = segment_speeds and 5 or 4','        local width = mixed_wrist and 6 or (segment_speeds and 5 or 4)')
    change('if not finite(x) or (j==5 and (x<=0 or x>speed or x>137)) then',
           'if not finite(x) or (j==5 and (x<=0 or x>speed or x>137)) or (j==6 and x~=0 and x~=1) then')
    change('        if joint_pivot then\n            for i=1,3 do', '''        if mixed_wrist then
            local previous = points.start
            for i=1,#points do
                local v = points[i]
                if v[6]==1 then
                    if v[5]~=137 then reply(false); return end
                    for j=1,3 do
                        if math.abs(v[j]-previous[j])>0.006 then reply(false); return end
                    end
                    if math.abs(v[4]-previous[4])>180.001 then reply(false); return end
                end
                previous=v
            end
        end
        if joint_pivot then
            for i=1,3 do''')
    change('            if joint_pivot then','            if joint_pivot or (mixed_wrist and v[6]==1) then')
    return text

def build(source=SOURCE,output=OUTPUT):
    with zipfile.ZipFile(source) as z:
        entries={i.filename:(copy.copy(i),z.read(i)) for i in z.infolist()}
    key='main/mod_Trajectory.lua';meta,raw=entries[key]
    entries[key]=(meta,candidate_lua(raw.decode('utf-8-sig')).encode())
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for meta,data in entries.values():z.writestr(meta,data)
    output.write_bytes(b'byrobot'+b.getvalue())
    with zipfile.ZipFile(output) as z:
        if z.testzip():raise ValueError('Archive validation failed.')
    d=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        changed=[key],base_protocol=220109,optional_mixed_wrist_capability=220111,old_pivot_capability=220110,
        commands='MoveL translations; fixed-XYZ MoveJ wrist turns at setting137; one final MOVFINISH',
        publish_required=True,hardware_tested=False,default_routes_changed=False)
    output.with_suffix('.manifest.json').write_text(json.dumps(d,indent=2));return d

if __name__=='__main__':print(json.dumps(build(),indent=2))
