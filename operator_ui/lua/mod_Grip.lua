-- Device 24 / 240101. Gripper only; Descend owns all arm positioning.
-- Uses the vendor __lif.lua primitive with ARRAY arguments, not JointTarget.
-- Force limits persist in the controller. Do not guess/reset them on exit.
local plan, token, ready, external
local VERSION=240101
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
function GripInit()
    plan,token,ready,external=nil,0,false,nil
end
local function unchanged(check_e1)
    local p,q=GetCRobT(T0,U0),GetCJoints()
    for i=1,4 do
        local v=GetElem(p,i==4 and 6 or i)
        if not finite(v) or math.abs(v-plan[i])>0.05 then return false end
        v=GetElem(q,i)
        if not finite(v) or math.abs(v-plan[i+4])>0.1 then return false end
    end
    for i=1,6 do
        local v=GetElem(q,i+6)
        if not finite(v) then return false end
        if (i>1 or check_e1) and math.abs(v-external[i])>0.05 then return false end
    end
    return true
end
local function report()
    local e=GetElem(GetCJoints(),7)
    local t=GetElem(GetCJointsTrq(),7)
    local n=GetElem(GetCJointsNormTrq(),7)
    if not finite(e) or not finite(t) or not finite(n) then return nil end
    SetSysInVarI(10,math.floor(e*1000+0.5))
    SetSysInVarI(11,math.floor(t*1000+0.5))
    SetSysInVarI(12,math.floor(n*1000+0.5))
    return {e,t,n}
end
function mod_Grip()
    ActionProcessedVar=1
    local op,incoming=SYSINVAR4,SYSINVAR2
    if op==6 then reply(VERSION); return end
    if op==1 then
        GripInit();plan={}
        for i=1,18 do
            plan[i]=GetSysParamF(i-1)
            if not finite(plan[i]) then fail(1); return end
        end
        -- XYZRz, J1..4, E1 floor, speed, six reviewed force limits,
        -- contact torque magnitude and sign. External positions are read here
        -- to preserve native units and every non-gripper external axis.
        external={}
        local q=GetCJoints()
        for i=1,6 do
            external[i]=GetElem(q,i+6)
            if not finite(external[i]) then fail(2);return end
        end
        if type(incoming)~='number' or incoming~=incoming or incoming%1~=0 or incoming<1
            or incoming>1073741823 or math.abs(plan[9]-3.8)>0.0001 or plan[10]<=0 or plan[10]>5
            or external[1]<27.98 or external[1]>28.05 or plan[17]<=0
            or (plan[18]~=-1 and plan[18]~=1) or plan[11]<=0 then fail(1); return end
        for i=11,16 do if plan[i]<0 then fail(1); return end end
        token,ready=incoming,true
        SetSysInVarI(7,token);SetSysInVarI(8,1);SetSysInVarI(9,0)
        reply(1);return
    end
    if op~=2 or not ready or incoming~=token then fail(1);return end
    ready=false -- a duplicate execute can never close again
    if not unchanged(true) then fail(2);return end
    if not report() then fail(3);return end
    SetSysInVarI(8,2)
    MoveExtJWithForce(
        DefArray(plan[9],external[2],external[3],external[4],external[5],external[6]),
        plan[10],DefArray(plan[11],plan[12],plan[13],plan[14],plan[15],plan[16]))
    MOVFINISH()
    -- Position may stop above the floor on contact. Never tighten again,
    -- automatically open, lift, or declare that a plate is safe to carry.
    SetSysInVarI(8,3)
    local last=nil
    for i=1,6 do
        DelayMS(100)
        if not unchanged(false) then fail(2);return end
        local v=report()
        if not v then fail(3);return end
        if v[1]<plan[9]-0.05 or v[1]>external[1]+0.05 then fail(4);return end
        if v[2]*plan[18]<plan[17] then fail(5);return end
        if last and math.abs(v[1]-last)>0.05 then fail(6);return end
        last=v[1]
    end
    SetSysInVarI(8,5);SetSysInVarI(9,0)
    reply(1)
end
