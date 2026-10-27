-- Cephla trajectory protocol v1. Device 22; no station or gripper actions.
-- Upload is nonmoving. Execute queues MoveL, with one final barrier.
-- Zone -1 is retained from the tested host-point executor, without guessed blending.
-- Stop is controller remoteStop, NOT PAUSE() (which drains motion first).
local points, expected, token, speed, checksum, ready, consumed
local MOD = 2147483629

function TrajectoryInit()
    points, expected, token, speed, checksum = {}, 0, 0, 0, 0
    ready, consumed = false, false
    SetSysInVarI(7, 0)
    SetSysInVarI(17, 220108)
    SetSysInVarI(18, 0) -- idle/uploading/committed/executing/done/error: 0..4,-1
    SetSysInVarI(19, 0) -- uploaded, then submitted count; NOT physical arrival
end

local function finite(x)
    return type(x) == 'number' and x == x and math.abs(x) < 100000
end

local function reply(ok)
    for i=0,6 do SetSysInVarI(i,0) end
    if not ok then
        ready, consumed = false, true
        SetSysInVarI(18,-1)
    end
    SendSysOutVarI(1, ok and 1 or -1)
end

local function addhash(h, x)
    return (h*31 + math.floor(x*100 + 0.5)) % MOD
end

function mod_Trajectory()
    ActionProcessedVar = 1
    local op, incoming = SYSINVAR4, SYSINVAR2
    if op == 6 then -- nonmoving protocol handshake, rules out stale version registers
        for i=0,6 do SetSysInVarI(i,0) end
        SendSysOutVarI(1,220108)
        return
    end
    if op == 1 then
        -- Begin: F0=count,F1=speed,F2=zone; F3..6=start pose,F7..10=start joints.
        TrajectoryInit()
        expected, speed = GetSysParamF(0), GetSysParamF(1)
        if not finite(expected) or expected%1~=0 or expected<1 or expected>1024
            or not finite(speed) or speed<=0 or speed>137 or GetSysParamF(2)~=-1
            or incoming<1 or incoming%1~=0 or incoming>1073741823 then
            reply(false); return
        end
        token = incoming
        points.start = {}
        for i=1,8 do
            points.start[i] = GetSysParamF(i+2)
            if not finite(points.start[i]) then reply(false); return end
        end
        SetSysInVarI(7,token)
        SetSysInVarI(18,1)
        reply(true); return
    end
    if incoming ~= token or token == 0 or consumed then reply(false); return end
    if op == 2 then
        local offset, count = SYSINVAR3, SYSINVAR5
        if ready or offset~=#points or count<1 or count>3 or count%1~=0
            or #points+count>expected then reply(false); return end
        local batch = {}
        for i=1,count do
            batch[i] = {}
            for j=1,4 do
                local x = GetSysParamF((i-1)*4+j-1)
                if not finite(x) then reply(false); return end
                batch[i][j] = x
            end
        end
        for i=1,count do
            points[#points+1] = batch[i]
            for j=1,4 do checksum=addhash(checksum,batch[i][j]) end
        end
        SetSysInVarI(19,#points)
        reply(true); return
    elseif op == 3 then
        if ready or #points~=expected or checksum~=SYSINVAR3 then
            reply(false); return
        end
        ready = true
        SetSysInVarI(18,2)
        reply(true); return
    elseif op == 4 then
        if not ready or #points~=expected then reply(false); return end
        ready, consumed = false, true
        local p, q = GetCRobT(T0,U0), GetCJoints()
        for i=1,4 do
            local idx = i==4 and 6 or i
            if not finite(GetElem(p,idx)) or not finite(GetElem(q,i))
                or math.abs(GetElem(p,idx)-points.start[i]) > (i==4 and 0.5 or 1)
                or math.abs(GetElem(q,i)-points.start[i+4]) > 0.5 then
                reply(false); return
            end
        end
        local e = {}
        for i=1,6 do e[i] = GetElem(q,i+6) end
        SetSysInVarI(18,3)
        SetSysInVarI(19,0)
        for i=1,#points do
            local v = points[i]
            MoveL(RobTarget(v[1],v[2],v[3],0,0,v[4],e[1],e[2],e[3],e[4],e[5],e[6]),speed,-1,T0,U0)
            SetSysInVarI(19,i)
        end
        MOVFINISH()
        SetSysInVarI(18,4)
        points = {}
        reply(true); return
    end
    reply(false)
end
