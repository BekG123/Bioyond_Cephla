"""Native MoveL corner blending for the pinned Hamilton route in both directions.

Uses the existing trajectory module, not an invented spline API. Zone lengths
are controller requests, not certified geometric radii or Bezier parameters.
"""
from pathlib import Path
from build_z77_transit_program import build as archive_build

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'controller/main_hostpoint_z77_transit_queue_220113.bin'
OUTPUT=ROOT/'controller/main_hostpoint_rounded_transit_queue_220114.bin'


def candidate_lua(text):
    text=text.replace('\r','')
    def change(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Unexpected Lua source: '+old)
        text=text.replace(old,new)
    change('mixed_wrist, blended_transit\n','mixed_wrist, blended_transit, rounded_transit\n')
    change('blended_transit = false, false, false, false, false, false',
           'blended_transit, rounded_transit = false, false, false, false, false, false, false')
    change('    if op == 18 then', '''    if op == 19 then -- nonmoving bidirectional rounded route capability
        for i=0,6 do SetSysInVarI(i,0) end
        SendSysOutVarI(1,220114)
        return
    end
    if op == 18 then''')
    change('or op == 16 then -- 8','or op == 16 or op == 20 then -- 8')
    change('segment_speeds = op == 8 or op == 12 or op == 16',
           'segment_speeds = op == 8 or op == 12 or op == 16 or op == 20\n        rounded_transit = op == 20')
    change('blended_transit = op == 16','blended_transit = op == 16 or op == 20')
    change('or op == 17 then\n','or op == 17 or op == 21 then\n')
    change('if (op == 17) ~= blended_transit or (op == 14) ~= mixed_wrist or ((op == 9 or op == 14 or op == 17) ~= segment_speeds)',
           'if (op == 21) ~= rounded_transit or ((op == 17 or op == 21) ~= blended_transit) or (op == 14) ~= mixed_wrist or ((op == 9 or op == 14 or op == 17 or op == 21) ~= segment_speeds)')
    change('(blended_transit and x~=-1 and x~=1)',
           '(blended_transit and x~=-1 and x~=1 and (not rounded_transit or x~=5))')
    change('        if blended_transit then\n', '''        if rounded_transit then
            if #points~=6 or speed~=137 then reply(false); return end
            local path={
                {306.20,-62.88,81.37,87.88},
                {306.20,-62.88,118.15,87.88},
                {310.26,-66.27,118.15,175.75},
                {345.03,-94.47,118.15,245.85},
                {345.03,-94.47,77.00,245.85},
                {372.43,-186.67,77.00,266.98},
                {372.43,-186.67,53.72,266.98}}
            local reverse=points[1][1]>370
            local start=path[reverse and 7 or 1]
            for j=1,4 do
                local delta=points.start[j]-start[j]
                if j==4 then delta=(delta+180)%360-180 end
                if math.abs(delta)>0.05 then reply(false); return end
            end
            local zones=reverse and {-1,5,1,1,-1,-1} or {-1,1,1,5,-1,-1}
            for i=1,6 do
                local target=path[reverse and (7-i) or (i+1)]
                for j=1,4 do
                    if math.abs(points[i][j]-target[j])>0.006 then reply(false); return end
                end
                local slow=(reverse and i==1) or (not reverse and i==6)
                if points[i][5]~=(slow and 5 or 137) or points[i][6]~=zones[i] then reply(false); return end
            end
        end
        if blended_transit and not rounded_transit then
''')
    return text


def build(source=SOURCE,output=OUTPUT):
    import json
    # Reuse the vendor archive writer; only mod_Trajectory.lua is replaced.
    result=archive_build(source,output,transform=candidate_lua)
    result.update(optional_rounded_transit_capability=220114,
        legacy_capabilities_preserved=[220109,220110,220111,220112,220113],
        segment_zones={'forward':[-1,1,1,5,-1,-1],'reverse':[-1,5,1,1,-1,-1]},
        segment_speeds={'forward':[137]*5+[5],'reverse':[5]+[137]*5},
        requested_final_turn_ceiling_mm=82,hardware_tested=False,
        source_documentation='C:/Bioyond/RobStudio/Config/BYCommand.json:785; Odin/user/__lif.lua:353,405,966-981',
        limitation='Native blend shape is not specified by the vendor. Z82 is a monitored trial constraint, not a certified bound from zone5. Analytic Bezier is offline comparison only; physical trial required.')
    result.pop('optional_z77_blended_transit_capability',None)
    output.with_suffix('.manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    import json
    print(json.dumps(build(),indent=2))
