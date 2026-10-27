-- Device 23, protocol 230101. One-shot vertical descent; never grips/retreats.
-- Torque is checked BETWEEN completed slow steps, not a force servo.
-- Fast approach ends 20 mm above the target. Built-in collision protection
-- remains active. Host monitors pose/faults and uses remoteStop on interruption.
local plan, token, ready
local VERSION = 230101
local function finite(v)
    return type(v)=='number' and v==v and math.abs(v)<100000
end
local function reply(value)
    for i=0,6 do SetSysInVarI(i,0) end
    SendSysOutVarI(1,value)
end
local function fail(reason)
    ready=false
    SetSysInVarI(8,-1); SetSysInVarI(9,reason)
    reply(-1)
end
function DescentInit()
    plan,token,ready=nil,0,false
    SetSysInVarI(8,0); SetSysInVarI(9,0)
end
local function pose_ok(z)
    local p=GetCRobT(T0,U0)
    for i=1,4 do
        local v=GetElem(p,i==4 and 6 or i)
        local expected=i==3 and z or plan[i]
        if not finite(v) or math.abs(v-expected)>(i==3 and 0.2 or 0.1) then return false end
    end
    return true
end
local function jaws_ok()
    local e=GetElem(GetCJoints(),7)
    return finite(e) and e>=plan[13]-0.02 and e<=plan[17]+0.05
end
local function torque()
    local q=GetCJointsNormTrq()
    local out,total={},0
    for i=1,4 do
        local v=GetElem(q,i)
        if not finite(v) then return nil end
        out[i]=math.floor(v*1000+0.5)
        total=total+math.abs(out[i])
        SetSysInVarI(12+i,out[i])
    end
    if total==0 then return nil end
    return out
end
local function move(z,speed,ext)
    if not jaws_ok() then return 4 end
    MoveL(RobTarget(plan[1],plan[2],z,0,0,plan[4],
        ext[1],ext[2],ext[3],ext[4],ext[5],ext[6]),speed,-1,T0,U0)
    MOVFINISH()
    if not pose_ok(z) then return 5 end
    return 0
end
function mod_Descent()
    ActionProcessedVar=1
    local op,incoming=SYSINVAR4,SYSINVAR2
    if op==6 then reply(VERSION); return end
    if op==1 then
        DescentInit()
        plan={}
        for i=1,17 do
            plan[i]=GetSysParamF(i-1)
            if not finite(plan[i]) then fail(1); return end
        end
        -- start XYZRz, start J1..4, goal Z, approach speed, probe speed,
        -- torque floor, required E1, envelope min/max Z, clearance, max E1.
        if type(incoming)~='number' or incoming~=incoming or incoming%1~=0 or incoming<1 or incoming>1073741823
            or plan[9]<plan[14] or plan[3]>plan[15] or plan[3]-plan[9]<0.5
            or plan[3]-plan[9]>350 or plan[10]<=0 or plan[10]>137
            or plan[11]<=0 or plan[11]>5 or plan[12]<25 or plan[12]>1000
            or plan[13]<0 or plan[13]>plan[17] or plan[17]<=0 or plan[17]>28
            or plan[16]~=20 then fail(1); return end
        token,ready=incoming,true
        SetSysInVarI(7,token); SetSysInVarI(8,1)
        reply(1); return
    end
    if op~=2 or not ready or incoming~=token then fail(1); return end
    ready=false -- consume BEFORE any motion; duplicates never run
    if not pose_ok(plan[3]) then fail(2); return end
    local q=GetCJoints()
    for i=1,4 do
        local v=GetElem(q,i)
        if not finite(v) or math.abs(v-plan[i+4])>0.5 then fail(2); return end
    end
    if not jaws_ok() then fail(4); return end
    if not torque() then fail(3); return end
    local ext={}
    for i=1,6 do
        ext[i]=GetElem(q,i+6)
        if not finite(ext[i]) then fail(2); return end
    end
    local z=plan[3]
    if z>plan[9]+20 then
        SetSysInVarI(8,2)
        local err=move(plan[9]+20,plan[10],ext)
        if err~=0 then fail(err); return end
        z=plan[9]+20
    end
    SetSysInVarI(8,3)
    local samples,mean,band={},{0,0,0,0},{}
    for n=1,5 do
        DelayMS(100)
        samples[n]=torque()
        if not samples[n] then fail(3); return end
        for i=1,4 do mean[i]=mean[i]+samples[n][i]/5 end
    end
    for i=1,4 do
        local variance=0
        for n=1,5 do variance=variance+(samples[n][i]-mean[i])^2/5 end
        band[i]=math.max(plan[12],3*math.sqrt(variance))
        -- Do not adapt the guard to arbitrarily noisy feedback.
        if band[i]>2*plan[12] then fail(3); return end
    end
    SetSysInVarI(8,4)
    local trend={}
    while z>plan[9]+0.0001 do
        if not pose_ok(z) then fail(5); return end
        local step=(z-plan[9]<=6.0001) and 0.5 or 1
        z=math.max(plan[9],z-step)
        local err=move(z,plan[11],ext)
        if err~=0 then fail(err); return end
        DelayMS(50)
        local reading=torque()
        if not reading then fail(3); return end
        -- Stationary J1 differs from moving J1. Preserve the proven local
        -- post-step trend; J2..4 guard the first step, all four thereafter.
        local ref=0
        for _,v in ipairs(trend) do ref=ref+v/#trend end
        for i=1,4 do
            local baseline=i==1 and ref or mean[i]
            if (i~=1 or #trend>0) and math.abs(reading[i]-baseline)>band[i] then
                fail(10+i); return -- no queued next step, retreat or grip
            end
        end
        trend[#trend+1]=reading[1]
        if #trend>3 then table.remove(trend,1) end
    end
    if not jaws_ok() then fail(4); return end
    SetSysInVarI(8,5); SetSysInVarI(9,0)
    reply(1)
end
