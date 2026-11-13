"""Extend the existing trajectory module with the bounded Z77 blend layout."""
import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'controller/main_hostpoint_blended_transit_queue_220112.bin'
OUTPUT=ROOT/'controller/main_hostpoint_z77_transit_queue_220113.bin'


def candidate_lua(text):
    text=text.replace('\r','')
    def change(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Unexpected Lua source: '+old)
        text=text.replace(old,new)
    change('    if op == 15 then', '''    if op == 18 then -- nonmoving Z77-layout capability; legacy queries unchanged
        for i=0,6 do SetSysInVarI(i,0) end
        SendSysOutVarI(1,220113)
        return
    end
    if op == 15 then''')
    change('            for i=1,6 do\n                local v=points[i]\n                local zone=(i==2 or i==3) and 1 or -1', '''            local z77 = points[3][6]==-1
            if z77 then
                -- Pin the new layout: complete the high turn before lowering,
                -- reach Z77 before turning/crossing; final seating stays exact.
                local expected = {
                    {306.20,-62.88,118.15,87.88},
                    {310.26,-66.27,118.15,175.75},
                    {345.03,-94.47,118.15,245.85},
                    {345.03,-94.47,77.00,245.85},
                    {372.43,-186.67,77.00,266.98},
                    {372.43,-186.67,53.72,266.98}}
                for i=1,6 do
                    for j=1,4 do
                        if math.abs(points[i][j]-expected[i][j])>0.006 then reply(false); return end
                    end
                end
            end
            for i=1,6 do
                local v=points[i]
                local zone=(i==2 or (i==3 and not z77)) and 1 or -1''')
    return text


def build(source=SOURCE,output=OUTPUT,*,transform=None):
    with zipfile.ZipFile(source) as z:entries={i.filename:(copy.copy(i),z.read(i)) for i in z.infolist()}
    key='main/mod_Trajectory.lua';meta,raw=entries[key]
    entries[key]=(meta,(transform or candidate_lua)(raw.decode('utf-8-sig')).encode())
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for meta,data in entries.values():z.writestr(meta,data)
    output.write_bytes(b'byrobot'+stream.getvalue())
    with zipfile.ZipFile(output) as z:
        if z.testzip():raise ValueError('Archive validation failed')
    result=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        changed=[key],optional_z77_blended_transit_capability=220113,legacy_capabilities_preserved=[220109,220110,220111,220112],
        segment_zones=[-1,1,-1,-1,-1,-1],segment_speeds=[137]*5+[5],completion_barriers=1,
        publish_required=True,hardware_tested=False,
        limitation='Only the level turn junction blends (1mm zone). Lowering to Z77 and final seating retain exact boundaries; uninterrupted velocity through all turns is not claimed.')
    output.with_suffix('.manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':print(json.dumps(build(),indent=2))
