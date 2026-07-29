-- version info:
-- v1.4.2408231900

--EXTENDED FUNCTIONS
function string.split(s, delimiter)
    t = {}
    for match in (s..delimiter):gmatch("(.-)"..delimiter) do
        table.insert(t, match)
    end
    return t
end

--DATA DEFINE
function MLOAD(mass,mcx,mcy,mcz,ixx,iyy,izz)
	return _DEF_LOAD(mass,mcx,mcy,mcz,ixx,iyy,izz)
end

function MTOOL(x, y, z, rx, ry, rz, mount)
	return _DEF_TOOL(x, y, z, rx, ry, rz, mount)
end

function MUSER(x, y, z, rx, ry, rz, mount)
	return _DEF_USER(x, y, z, rx, ry, rz, mount)
end

function MARRAY(a1, a2, a3, a4, a5, a6)
	return _DEF_ARRAY(a1, a2, a3, a4, a5, a6)
end

function MJOINT(j1, j2, j3, j4, j5, j6, e1, e2, e3, e4, e5, e6)
	return _JOINT_TARGET(j1, j2, j3, j4, j5, j6, e1, e2, e3, e4, e5, e6)
end

function MJOINT2(j, e1, e2, e3, e4, e5, e6)
	return _JOINT_TARGET2(j, e1, e2, e3, e4, e5, e6)
end

function MFRAME(x, y, z, rx, ry, rz, e1, e2, e3, e4, e5, e6)
	return _ROB_TARGET (x, y, z, rx, ry, rz, e1, e2, e3, e4, e5, e6)
end

function MFRAME2(p, e1, e2, e3, e4, e5, e6)
	return _ROB_TARGET (p, e1, e2, e3, e4, e5, e6)
end

function GETFRAME(tool, user)
	return _GET_CUR_ROBT(tool, user)
end

function GETJOINTS()
	return _GET_CUR_JOINTS()
end

function GETREFJOINTS()
	return _GET_CUR_REF_JOINTS()
end

function GETJOINTSVEL()
	return _GET_CUR_JOINTS_VEL()
end

function GETJOINTSTRQ()
	return _GET_CUR_JOINTS_TRQ()
end

function GETJOINTSNORMTRQ()
    return _GET_CUR_JOINTS_NORM_TRQ()
end

-- SYSTEM API

function PRINT(E)
	_ROB_PRINT(GETSTRING(E))
end

function GETTYPE(E)
	local var = type(E)
	if(var == "userdata") then
		local type1 = _GET_USER_TYPE(E)
		if type1 == "UNKNOWN" then
			type1 = _GET_LIQ_USER_TYPE(E)
		end
		return type1
	else
		if(var == "table" and E._type ~= nil) then
			var = E._type
		end
		return var
	end
end

function GETSTRING(E)
	local var = GETTYPE(E)
	--_ROB_PRINT(var)
	if(var == "nil") then
		return "nil"
	elseif(var == "number") then
		return string.format("%s",E)
	elseif(var == "string") then
		return E
	elseif(var == "table") then
		local str = "{"
		for k,v in pairs(E) do
			str = str..tostring(k)..":"..GETSTRING(v).." "
		end
		str = str.."}"
		return str
	elseif(var == "boolean") then
		return tostring(E)
	elseif(var == "TOOL") then
		return string.format("TOOL:X(%s)Y(%s)Z(%s)RX(%s)RY(%s)RZ(%s)MOUNT(%s)",E._x,E._y,E._z,E._rx,E._ry,E._rz,E._mounting)
	elseif(var == "USER") then
		return string.format("USER:X(%s)Y(%s)Z(%s)RX(%s)RY(%s)RZ(%s)MOUNT(%s)",E._x,E._y,E._z,E._rx,E._ry,E._rz,E._mounting)
	elseif(var == "LOAD") then
		return string.format("LOAD:M(%s)MCX(%s)MCY(%s)MCZ(%s)ICXX(%s)ICYY(%s)ICZZ(%s)",E._mass,E._mcx,E._mcy,E._mcz,E._icxx,E._icyy,E._iczz)
	elseif(var == "FRAME") then
		return string.format("FRAME:X(%g)Y(%g)Z(%g)RX(%g)RY(%g)RZ(%g)EXTJ(%g,%g,%g,%g,%g,%g,%g,%g)",E._x,E._y,E._z,E._rx,E._ry,E._rz,E._ext1,E._ext2,E._ext3,E._ext4,E._ext5,E._ext6,E._ext7,E._ext8)
	elseif(var == "JOINT") then
		return string.format("JOINT:J(%g,%g,%g,%g,%g,%g,%g,%g)EXTJ(%g,%g,%g,%g,%g,%g,%g,%g)",E._j1,E._j2,E._j3,E._j4,E._j5,E._j6,E._j7,E._j8,E._ext1,E._ext2,E._ext3,E._ext4,E._ext5,E._ext6,E._ext7,E._ext8)
	elseif(var == "ARRAY") then
		return string.format("ARRAY:A(%s,%s,%s,%s,%s,%s,%s,%s)",E._a1,E._a2,E._a3,E._a4,E._a5,E._a6,E._a7,E._a8)
	elseif(var == "PALLET") then
		return string.format("PALLET:layerNum(%s)plateNum(%s)totalHeight(%s)",E._layerNum,E._plateNum,E._totalHeight)
	elseif(var == "LTARGET") then
		return string.format("LiqTarget:slotLoc(%s) colNo(%s) rowNo(%s)", E.slotLoc, E.colNo, E.rowNo)
	elseif(var == "LCONPARA") then
		return string.format("LiqConPara:volume(%s) speed(%s) zLoc(%s) mixType(%s) delayTime(%s) zLiqLevel(%s) liqLevelDet(%s) liqLevelFollow(%s)", E.volume,E.speed,E.zLoc,E.mixType,E.delayTime, E.zLiqLevel, E.liqLevelDet, E.liqLevelFollow)
	elseif(var == "LTCHPARA") then
		return string.format("LiqTchPara:speed(%s) zLoc(%s) inHoleLoc(%s) opTime(%s)",E.speed,E.zLoc,E.inHoleLoc,E.opTime)
	elseif(var == "LAGAPPARA") then
		return string.format("LiqAirGapPara:volume(%s) speed(%s) zLoc(%s)",E.volume,E.speed,E.zLoc)
	elseif(var == "LS32ARRAY") then
		return string.format("LiqS32Array:a1(%s)a2(%s)a3(%s)a4(%s)a5(%s)a6(%s)a7(%s)a8(%s)a9(%s)a10(%s)",E.a1,E.a2,E.a3,E.a4,E.a5,E.a6,E.a7,E.a8,E.a9,E.a10)
	elseif(var == "LLYTINFO") then
		return string.format("LiqLayoutInfo:SlotLoc(%s-%s-%s-%s-%s-%s-%s-%s-%s-%s)\nTypeId(%s-%s-%s-%s-%s-%s-%s-%s-%s-%s)",E.modSlotLoc1,E.modSlotLoc2,E.modSlotLoc3,E.modSlotLoc4,E.modSlotLoc5,E.modSlotLoc6,E.modSlotLoc7,E.modSlotLoc8,E.modSlotLoc9,E.modSlotLoc10,E.modTypeId1,E.modTypeId2,E.modTypeId3,E.modTypeId4,E.modTypeId5,E.modTypeId6,E.modTypeId7,E.modTypeId8,E.modTypeId9,E.modTypeId10)
	elseif(var == "LMODINSD") then
		return string.format("LiqModInsData:a1(%s)a2(%s)a3(%s)a4(%s)a5(%s)",E.a1,E.a2,E.a3,E.a4,E.a5)
	elseif(var == "LJOBDATA") then
		return string.format("LiqJobData:a1(%s)a2(%s)a3(%s)a4(%s)a5(%s)a6(%s)a7(%s)a8(%s)a9(%s)a10(%s)\na11(%s)a12(%s)a13(%s)a14(%s)a15(%s)a16(%s)a17(%s)a18(%s)a19(%s)a20(%s)\na21(%s)a22(%s)a23(%s)a24(%s)a25(%s)a26(%s)a27(%s)a28(%s)a29(%s)a30(%s)",E.a1,E.a2,E.a3,E.a4,E.a5,E.a6,E.a7,E.a8,E.a9,E.a10,E.a11,E.a12,E.a13,E.a14,E.a15,E.a16,E.a17,E.a18,E.a19,E.a20,E.a21,E.a22,E.a23,E.a24,E.a25,E.a26,E.a27,E.a28,E.a29,E.a30)
	elseif(var == "LJOBREF") then
		return string.format("LiqJobRef:jobName(%s)\na1(%s)a2(%s)a3(%s)a4(%s)a5(%s)a6(%s)a7(%s)a8(%s)a9(%s)a10(%s)\na11(%s)a12(%s)a13(%s)a14(%s)a15(%s)a16(%s)a17(%s)a18(%s)a19(%s)a20(%s)\na21(%s)a22(%s)a23(%s)a24(%s)a25(%s)a26(%s)a27(%s)a28(%s)a29(%s)a30(%s)",E.jobName,E.jobData1,E.jobData2,E.jobData3,E.jobData4,E.jobData5,E.jobData6,E.jobData7,E.jobData8,E.jobData9,E.jobData10,E.jobData11,E.jobData12,E.jobData13,E.jobData14,E.jobData15,E.jobData16,E.jobData17,E.jobData18,E.jobData19,E.jobData20,E.jobData21,E.jobData22,E.jobData23,E.jobData24,E.jobData25,E.jobData26,E.jobData27,E.jobData28,E.jobData29,E.jobData30)
	elseif(var == "LJOBFBK") then
		return string.format("LiqJobFbk:jobName(%s) ret(%s)",E.jobName,E.jobRet)
	else
		return "UNKNOWN"
	end
end

function GETTIME()
	return _GET_TIME_MS()
end

function TIMER(timeMS)
	local startTime = _GET_TIME_MS()
	local endTime = startTime + timeMS

	while 1 do
		local curTime = _GET_TIME_MS()
		if curTime >= startTime and curTime < endTime then
			_DELAY_1MS()
		else
			return
		end
	end
end

function SAVEDATA(data)
	_SAVE_DATA(data)
end

function LOADDATA()
	return _LOAD_DATA()
end

function PAUSE()
	MOVFINISH()
	_PAUSE()
end

function READREG(id)
	return _READ_REG(id)
end

function WRITEREG(id, value)
	return _WRITE_REG(id, value)
end

function WAITREG(id, value, time)
	local startTime = _GET_TIME_MS()
	local endTime = startTime + time
	while 1 do
		local ret = _READ_REG(id)
		if ret ~= value then
			if time > 0 then
				local curTime = _GET_TIME_MS()
				if curTime < startTime or curTime >= endTime then
					PRINT("WAITREG timeout")
					PAUSE()
				end
			end
			TIMER(10)
		else
			return
		end
	end
end

-- OPERATION API

function INC(value)
	return _MATH_INC(value)
end

function DEC(value)
	return _MATH_DEC(value)
end

function SIN(value)
	return _MATH_SIN(value)
end

function COS(value)
	return _MATH_COS(value)
end

function TAN(value)
	return _MATH_TAN(value)
end

function ASIN(value)
	return _MATH_ASIN(value)
end

function ACOS(value)
	return _MATH_ACOS(value)
end

function ATAN(value)
	return _MATH_ATAN(value)
end

function SQRT(value)
	return _MATH_SQRT(value)
end

function GETE(data, pos)
	return _GET_ELEM(data, pos)
end

function SETE(data, pos, value)
	_SET_ELEM(data, pos, value)
end

function GETPOSE(data, pos)
	return _GET_ELEM(data, pos)
end

function SETPOSE(data, pos, value)
	return _SET_ELEM(data, pos, value)
end

function IDIV(num, den)
	if (type(num) ~= "number" or type(den) ~= "number") then
		GOTOERROR("num and den should be number")
		return
	end
	if den == 0 then
		GOTOERROR("den is 0, invalid")
		return
	end
	return math.floor(num/den)
end


-- BIT OPERATION API
function BITAND(data1, data2)
	return _BIT_AND(data1, data2)
end

function BITOR(data1, data2)
	return _BIT_OR(data1, data2)
end

function BITNOT(data1)
	return _BIT_NEG(data1)
end

function BITXOR(data1, data2)
	return _BIT_XOR(data1, data2)
end

function BITCLR(data1, data2)
	return _BIT_CLEAR(data1, data2)
end

function BITSET(data1, data2)
	return _BIT_SET(data1, data2)
end

function BITCHK(data1, data2)
	return _BIT_CHECK(data1, data2)
end

function BITLSH(data1, data2)
	return _BIT_LSH(data1, data2)
end

function BITRSH(data1, data2)
	return _BIT_RSH(data1, data2)
end

-- MOTION API

function MOVEXTJ(j,speed,zone,tool,user)
	while 1 do
		local ret = _MOVE_EXTJ(j,speed,zone,tool,user)
		if ret == 0 or ret == -1 then
			TIMER(10)
		else
			return 1
		end
	end
end

function MOVABSJ(j,speed,zone)
	while 1 do
		local ret = _MOVE_ABSJ(j,speed,zone)
		if ret == 0 or ret == -1 then
			TIMER(10)
		else
			return 1
		end
	end
end

function MOVJ(p,speed,zone,tool,user)
	while 1 do
		local ret = _MOVE_J(p,speed,zone,tool,user)
		if ret == 0 or ret == -1 then
			TIMER(10)
		else
			return 1
		end
	end
end

function MOVL(p,speed,zone,tool,user)
	while 1 do
		local ret = _MOVE_L(p,speed,zone,tool,user)
		if ret == 0 or ret == -1 then
			TIMER(10)
		else
			return 1
		end
	end
end

function MOVC(viap,endp,speed,zone,tool,user)
	while 1 do
		local ret = _MOVE_C(viap,endp,speed,zone,tool,user)
		if ret == 0 or ret == -1 then
			TIMER(10)
		else
			return 1
		end
	end
end

function MOVRD(rec_id, vel)
	while 1 do
		local ret = _MOVE_REC(rec_id, vel)
		if ret == 0 then
			TIMER(10)
		else
			break
		end
	end
	while 1 do
		local ret = _PLAY_DONE()
		if ret == 0 then
			TIMER(10)
		else
			return 1
		end
	end
end

function MOVALL()
	while 1 do
		local ret = _MOVE_ALL()
		if ret == 0 then
			TIMER(10)
		else
			return
		end
	end
end

function MOVFINISH()
	MOVALL()
	while 1 do
		local ret = _IS_MOVING()
		if ret == 1 then
			TIMER(10)
		else
			return
		end
	end
end

function MOVLOAD(load)
	_SET_LOAD(load)
end

function MOVACC(acc, jerk)
	_SET_ACC(acc, jerk)
end

function SETACCTIME(time)
	_SET_ACC_TIME(time)
end

function SETTUNEMODE()
	_SET_TUNE_MODE(1)
end

function CLEARTUNEMODE()
	_SET_TUNE_MODE(0)
end

function TOOLSFT(sft)
	_SHIFT_TOOL(sft)
end

function USERSFT(sft)
	_SHIFT_USER(sft)
end

function SPEED(spd)
	_SET_SPEED_SCALE(spd)
end

function ENABLEGRIPPERDET(modIndex)
	MOVFINISH()
	_ENABLE_GRIPPER_DET(modIndex)
end

function DISABLEGRIPPERDET(modIndex)
	MOVFINISH()
	_DISABLE_GRIPPER_DET(modIndex)
end

-- IO API
function VPULSE(pin, time)
	MOVFINISH()
	VDOUT(pin,1)
	TIMER(time)
	VDOUT(pin,0)
end

function VWAIT(pin, value, time)
	MOVFINISH()
	local startTime = _GET_TIME_MS()
	local endTime = startTime + time
	while 1 do
		local ret = _READ_VIR_DI(pin)
		if ret ~= value then
			if time > 0 then
				local curTime = _GET_TIME_MS()
				if curTime < startTime or curTime >= endTime then
					PRINT("VWAIT timeout")
					PAUSE()
				end
			end
			TIMER(10)
		else
			return
		end
	end
end

function VDIN(pin)
	MOVFINISH()
	return _READ_VIR_DI(pin)
end

function VDOUT(pin, value)
	MOVFINISH()
	_WRITE_VIR_DO(pin, value)
end

function PULSE(pin, time)
	MOVFINISH()
	DOUT(pin,1)
	TIMER(time)
	DOUT(pin,0)
end

function WAIT(pin, value, time)
	MOVFINISH()
	local startTime = _GET_TIME_MS()
	local endTime = startTime + time
	while 1 do
		local ret = _READ_DI(pin)
		if ret ~= value then
			if time > 0 then
				local curTime = _GET_TIME_MS()
				if curTime < startTime or curTime >= endTime then
					PRINT("WAIT timeout")
					PAUSE()

				end
			end
			TIMER(10)
		else
			return
		end
	end
end

function DIN(pin)
	MOVFINISH()
	return _READ_DI(pin)
end

function DOUT(pin, value)
	MOVFINISH()
	_WRITE_DO(pin, value)
end

function AIN(pin)
	MOVFINISH()
	return _READ_AI(pin)
end

function AOUT(pin, value)
	MOVFINISH()
	_WRITE_AO(pin, value)
end

--pallet operations

function GOTOERROR(str)
	_GOTO_ERROR(str)
end

Pallet = nil--[[
				["基座尺寸"]:{1000,1000,10}
				["垛尺寸"]:{500,500,200}
				["层数"]:5,
				["排样数"]:2,
				["总高度"]:500,
				["排样垛数"]:{4,4}
				["各层高度"]:{0,100,200,300,400},
				["各层排样"]:{1,2,1,2,1},
				["各层过渡点偏移"]:{0,100,200,300,400},
				["排样表"]:{
						[1]:{
							[1]:{["准备"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["放件"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["离开"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0}},
							[2]:{["准备"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["放件"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["离开"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0}},
							[3]:{["准备"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["放件"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["离开"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0}},
							[4]:{["准备"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["放件"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["离开"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0}}
						},
						[2]:{
							[1]:{["准备"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["放件"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["离开"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0}},
							[2]:{["准备"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["放件"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["离开"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0}},
							[3]:{["准备"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["放件"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["离开"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0}},
							[4]:{["准备"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["放件"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0},
							["离开"]:{["x"]:0,["y"]:0,["z"]:0,["rx"]:0,["ry"]:0,["rz"]:0}}
						}
					}
				["参考点"]:{0,0,0,0,0,0,0,0,0,0,0,0}
				["过渡点"]:{0,0,0,0,0,0,0,0,0,0,0,0}
			]]

function MPALLET(baseSize,stackSize,layerNum,plateNum,totalHeight,perPlateNum,perLayHeight,perPlate,perTransitHeight,plateStyle,refPoint,transitPoint)
	if(type(baseSize) ~= "table" or table.getn(baseSize) ~= 3) then
		GOTOERROR("base size is wrong")
		return nil
	end
	for i = 1, table.getn(baseSize), 1 do
		if(type(baseSize[i]) ~= "number" or baseSize[i] < 0) then
			GOTOERROR("base size should bigger than 0")
			return nil
		end
	end
	if(type(stackSize) ~= "table" or table.getn(stackSize) ~= 3) then
		GOTOERROR("base size is wrong")
		return nil
	end
	for i = 1, table.getn(stackSize), 1 do
		if(type(stackSize[i]) ~= "number" or stackSize[i] < 0) then
			GOTOERROR("base size should bigger than 0")
			return nil
		end
	end
	if(type(layerNum) ~= "number" or layerNum <= 0) then
		GOTOERROR("Layer number should bigger than 0")
		return nil
	end
	if(type(plateNum) ~= "number" or plateNum <= 0) then
		GOTOERROR("Plate number should bigger than 0")
		return nil
	end
	if(type(totalHeight) ~= "number" or totalHeight <= 0) then
		GOTOERROR("Total height should bigger than 0")
		return nil
	end
	if(type(perPlateNum) ~= "table" or table.getn(perPlateNum) ~= plateNum) then
		GOTOERROR("Stack number is wrong")
		return nil
	end
	for i = 1, table.getn(perPlateNum), 1 do
		if(type(perPlateNum[i]) ~= "number" or perPlateNum[i] <= 0) then
			GOTOERROR("Stack number should bigger than 0")
			return nil
		end
	end
	if(type(perLayHeight) ~= "table" or table.getn(perLayHeight) ~= layerNum) then
		GOTOERROR("Height number is wrong")
		return
	end
	for i = 1, table.getn(perLayHeight), 1 do
		if(type(perLayHeight[i]) ~= "number" or perLayHeight[i] < 0) then
			GOTOERROR("Height should bigger than 0")
			return nil
		end
	end
	if(type(perPlate) ~= "table" or table.getn(perPlate) ~= layerNum) then
		GOTOERROR("Plate unit is wrong")
		return
	end
	for i = 1, table.getn(perPlate), 1 do
		if(type(perPlate[i]) ~= "number" or perPlate[i] <= 0) then
			GOTOERROR("Plate unit should bigger than 0")
			return nil
		end
	end
	if(type(perTransitHeight) ~= "table" or table.getn(perTransitHeight) ~= layerNum) then
		GOTOERROR("Transit Height number is wrong")
		return
	end
	for i = 1, table.getn(perTransitHeight), 1 do
		if(type(perTransitHeight[i]) ~= "number" or perTransitHeight[i] < 0) then
			GOTOERROR("Transit Height should bigger than 0")
			return nil
		end
	end
	if(type(plateStyle) ~= "table" or table.getn(plateStyle) ~= plateNum) then
		GOTOERROR("The number of plate style is wrong")
		return nil
	end
	for i = 1, plateNum, 1 do
		if(type(plateStyle[i]) ~= "table") then
			GOTOERROR("Plate style is not a table")
			return nil
		end
		for j = 1, perPlateNum[i], 1 do
			if(type(plateStyle[i][j]) ~= "table") then
				GOTOERROR("Stack is wrong")
				return nil
			end
			for k = 1, 3, 1 do
				if(type(plateStyle[i][j][k]) ~= "table") then
					GOTOERROR("Stack data is wrong")
					return nil
				end
				for l = 1, 6, 1 do
					if(type(plateStyle[i][j][k][l]) ~= "number") then
						GOTOERROR("Offset is wrong")
						return nil
					end
				end
			end
		end
	end
	if(type(refPoint) ~= "table" or table.getn(refPoint) ~= 12) then
		GOTOERROR("RefPint is wrong")
		return nil
	end
	if(type(transitPoint) ~= "table" or table.getn(transitPoint) ~= 12) then
		GOTOERROR("TransitPoint is wrong")
		return nil
	end
	local pallet = {}
	pallet._type = "PALLET"
	pallet._baseSize = {}
	pallet._baseSize._length = baseSize[1]
	pallet._baseSize._width = baseSize[2]
	pallet._baseSize._height = baseSize[3]
	pallet._stackSize = {}
	pallet._stackSize._length = stackSize[1]
	pallet._stackSize._width = stackSize[2]
	pallet._stackSize._height = stackSize[3]
	pallet._layerNum = layerNum
	pallet._plateNum = plateNum
	pallet._totalHeight = totalHeight
	pallet._perPlateNum = perPlateNum
	pallet._perLayHeight = perLayHeight
	pallet._perPlate = perPlate
	pallet._perTransitHeight = perTransitHeight
	pallet._plateStyle = {}
	for i = 1, plateNum, 1 do
		pallet._plateStyle[i] = {}
		for j = 1, perPlateNum[i], 1 do
			pallet._plateStyle[i][j] = {}
			pallet._plateStyle[i][j]._pre = {}
			pallet._plateStyle[i][j]._put = {}
			pallet._plateStyle[i][j]._lev = {}
			pallet._plateStyle[i][j]._pre._x = plateStyle[i][j][1][1]
			pallet._plateStyle[i][j]._pre._y = plateStyle[i][j][1][2]
			pallet._plateStyle[i][j]._pre._z = plateStyle[i][j][1][3]
			pallet._plateStyle[i][j]._pre._rx = plateStyle[i][j][1][4]
			pallet._plateStyle[i][j]._pre._ry = plateStyle[i][j][1][5]
			pallet._plateStyle[i][j]._pre._rz = plateStyle[i][j][1][6]
			pallet._plateStyle[i][j]._put._x = plateStyle[i][j][2][1]
			pallet._plateStyle[i][j]._put._y = plateStyle[i][j][2][2]
			pallet._plateStyle[i][j]._put._z = plateStyle[i][j][2][3]
			pallet._plateStyle[i][j]._put._rx = plateStyle[i][j][2][4]
			pallet._plateStyle[i][j]._put._ry = plateStyle[i][j][2][5]
			pallet._plateStyle[i][j]._put._rz = plateStyle[i][j][2][6]
			pallet._plateStyle[i][j]._lev._x = plateStyle[i][j][3][1]
			pallet._plateStyle[i][j]._lev._y = plateStyle[i][j][3][2]
			pallet._plateStyle[i][j]._lev._z = plateStyle[i][j][3][3]
			pallet._plateStyle[i][j]._lev._rx = plateStyle[i][j][3][4]
			pallet._plateStyle[i][j]._lev._ry = plateStyle[i][j][3][5]
			pallet._plateStyle[i][j]._lev._rz = plateStyle[i][j][3][6]
		end
	end
	pallet._refPoint = {}
	pallet._refPoint.frame = {}
	pallet._refPoint.frame._x = refPoint[1]
	pallet._refPoint.frame._y = refPoint[2]
	pallet._refPoint.frame._z = refPoint[3]
	pallet._refPoint.frame._rx = refPoint[4]
	pallet._refPoint.frame._ry = refPoint[5]
	pallet._refPoint.frame._rz = refPoint[6]
	pallet._refPoint.ext = {}
	pallet._refPoint.ext[1] = refPoint[7]
	pallet._refPoint.ext[2] = refPoint[8]
	pallet._refPoint.ext[3] = refPoint[9]
	pallet._refPoint.ext[4] = refPoint[10]
	pallet._refPoint.ext[5] = refPoint[11]
	pallet._refPoint.ext[6] = refPoint[12]
	pallet._transitPoint = {}
	pallet._transitPoint.frame = {}
	pallet._transitPoint.frame._x = transitPoint[1]
	pallet._transitPoint.frame._y = transitPoint[2]
	pallet._transitPoint.frame._z = transitPoint[3]
	pallet._transitPoint.frame._rx = transitPoint[4]
	pallet._transitPoint.frame._ry = transitPoint[5]
	pallet._transitPoint.frame._rz = transitPoint[6]
	pallet._transitPoint.ext = {}
	pallet._transitPoint.ext[1] = transitPoint[7]
	pallet._transitPoint.ext[2] = transitPoint[8]
	pallet._transitPoint.ext[3] = transitPoint[9]
	pallet._transitPoint.ext[4] = transitPoint[10]
	pallet._transitPoint.ext[5] = transitPoint[11]
	pallet._transitPoint.ext[6] = transitPoint[12]
	return pallet
end

function PALLETSET(pallet)
	if(type(pallet) ~= "table" or pallet._type ~= "PALLET") then
		GOTOERROR("Pallet can't be null")
		return
	end
	Pallet = pallet
end

function getIndex(n,perPlateNum,perPlate)
	local num = 0
	local index1 = 0
	local index2 = 0
	for i = 1, table.getn(perPlate),1 do
		num = num + perPlateNum[perPlate[i]]
		if(num >= n) then
			index1 = i
			index2 = n - (num - perPlateNum[perPlate[i]])
			break
		end
	end
	return index1,index2
end

function PALLETGETTSPOINT(n)
	if(type(n) ~= "number" or n <= 0) then
		GOTOERROR("Parameter should bigger than 0")
		return
	end
	if(type(Pallet) ~= "table" or Pallet._type ~= "PALLET") then
		GOTOERROR("Pallet can't be null")
		return
	end
	local index1,index2 = getIndex(n,Pallet._perPlateNum,Pallet._perPlate)
	if(index1 == 0 or index2 == 0) then
		GOTOERROR("Can't find the stack")
		return
	end
	local height = Pallet._perTransitHeight[index1]
	local p = MFRAME(Pallet._transitPoint.frame._x,Pallet._transitPoint.frame._y,Pallet._transitPoint.frame._z+height,Pallet._transitPoint.frame._rx,Pallet._transitPoint.frame._ry,Pallet._transitPoint.frame._rz,Pallet._transitPoint.ext[1],Pallet._transitPoint.ext[2],Pallet._transitPoint.ext[3],Pallet._transitPoint.ext[4],Pallet._transitPoint.ext[5],Pallet._transitPoint.ext[6])
	return p
end

function PALLETGETPOINT(n)
	if(type(n) ~= "number" or n <= 0) then
		GOTOERROR("Parameter should bigger than 0")
		return
	end
	if(type(Pallet) ~= "table" or Pallet._type ~= "PALLET") then
		GOTOERROR("Pallet can't be null")
		return
	end
	local index1,index2 = getIndex(n,Pallet._perPlateNum,Pallet._perPlate)
	if(index1 == 0 or index2 == 0) then
		GOTOERROR("Can't find the stack")
		return
	end
	local height = Pallet._perLayHeight[index1]
	local pre = Pallet._plateStyle[Pallet._perPlate[index1]][index2]._pre
	local put = Pallet._plateStyle[Pallet._perPlate[index1]][index2]._put
	local lev = Pallet._plateStyle[Pallet._perPlate[index1]][index2]._lev
	local putP = MFRAME(Pallet._refPoint.frame._x+put._x,Pallet._refPoint.frame._y+put._y,Pallet._refPoint.frame._z+put._z+height,Pallet._refPoint.frame._rx+put._rx,Pallet._refPoint.frame._ry+put._ry,Pallet._refPoint.frame._rz+put._rz,Pallet._refPoint.ext[1],Pallet._refPoint.ext[2],Pallet._refPoint.ext[3],Pallet._refPoint.ext[4],Pallet._refPoint.ext[5],Pallet._refPoint.ext[6])
	local preP = MFRAME(Pallet._refPoint.frame._x+pre._x+put._x,Pallet._refPoint.frame._y+pre._y+put._y,Pallet._refPoint.frame._z+pre._z+put._z+height,Pallet._refPoint.frame._rx+pre._rx+put._rx,Pallet._refPoint.frame._ry+pre._ry+put._ry,Pallet._refPoint.frame._rz+pre._rz+put._rz,Pallet._refPoint.ext[1],Pallet._refPoint.ext[2],Pallet._refPoint.ext[3],Pallet._refPoint.ext[4],Pallet._refPoint.ext[5],Pallet._refPoint.ext[6])
	local levP = MFRAME(Pallet._refPoint.frame._x+lev._x+put._x,Pallet._refPoint.frame._y+lev._y+put._y,Pallet._refPoint.frame._z+lev._z+put._z+height,Pallet._refPoint.frame._rx+lev._rx+put._rx,Pallet._refPoint.frame._ry+lev._ry+put._ry,Pallet._refPoint.frame._rz+lev._rz+put._rz,Pallet._refPoint.ext[1],Pallet._refPoint.ext[2],Pallet._refPoint.ext[3],Pallet._refPoint.ext[4],Pallet._refPoint.ext[5],Pallet._refPoint.ext[6])
	return putP,preP,levP
end

--global definition
tool0=MTOOL(0,0,0,0,0,0,0)
user0=MUSER(0,0,0,0,0,0,1)
load0=MLOAD(0,0,0,0,0,0,0)
T0=MTOOL(0,0,0,0,0,0,0)
U0=MUSER(0,0,0,0,0,0,1)
LOAD0=MLOAD(0,0,0,0,0,0,0)
COORD1=MUSER(0,0,0,0,0,0,11)
COORD2=MUSER(0,0,0,0,0,0,12)
COORD3=MUSER(0,0,0,0,0,0,13)
COORD4=MUSER(0,0,0,0,0,0,14)
COORD5=MUSER(0,0,0,0,0,0,15)
COORD6=MUSER(0,0,0,0,0,0,16)
COORD7=MUSER(0,0,0,0,0,0,17)
COORD8=MUSER(0,0,0,0,0,0,18)
COORD12=MUSER(0,0,0,0,0,0,19)
COORD123=MUSER(0,0,0,0,0,0,20)
X=1
Y=2
Z=3
RX=4
RY=5
RZ=6

--
-- @breif: jump to the target with a gate shape motion.
-- @param h1: the maximum height
-- @param h2: rising height
-- @param h3: descent height
function JUMP(p,h1,h2,h3,speed,zone,tool,user)
	MOVFINISH()
	local LP0=_GET_FRAME_IN_SHIFT(tool,user)
	local LP1=MFRAME(p._x,p._y,p._z+h1,p._rx,p._ry,p._rz,p._ext1,p._ext2,p._ext3,p._ext4,p._ext5,p._ext6)
	if (h1 < h2 or h1 < h3) then
		GOTOERROR("h1不能比h2或者h3小")
		return
	end
	if (h1 <= 0 or h2 <=0 or h3 <= 0) then
		GOTOERROR("高度参数必须大于0")
		return
	end
	LP0._z=LP0._z+h1
	MOVL(LP0,speed,h1-h2,tool,user)
	MOVL(LP1,speed,h1-h3,tool,user)
	MOVL(p,speed,zone,tool,user)
end

--system variables definition
SYSINVAR0=0
SYSINVAR1=0
SYSINVAR2=0
SYSINVAR3=0
SYSINVAR4=0
SYSINVAR5=0
SYSINVAR6=0
SYSINVAR7=0
SYSINVAR8=0
SYSINVAR9=0
SYSINVAR10=0
SYSINVAR11=0
SYSINVAR12=0
SYSINVAR13=0
SYSINVAR14=0
SYSINVAR15=0
SYSINVAR16=0
SYSINVAR17=0
SYSINVAR18=0
SYSINVAR19=0
SYSOUTVAR={0,0,0,0,0,0,0,0,0,0}

function GETSYSINVARI()
	SYSINVAR0 = _GET_SYS_VAR_I(0)
	SYSINVAR1 = _GET_SYS_VAR_I(1)
	SYSINVAR2 = _GET_SYS_VAR_I(2)
	SYSINVAR3 = _GET_SYS_VAR_I(3)
	SYSINVAR4 = _GET_SYS_VAR_I(4)
	SYSINVAR5 = _GET_SYS_VAR_I(5)
	SYSINVAR6 = _GET_SYS_VAR_I(6)
	SYSINVAR7 = _GET_SYS_VAR_I(7)
	SYSINVAR8 = _GET_SYS_VAR_I(8)
	SYSINVAR9 = _GET_SYS_VAR_I(9)
	SYSINVAR10 = _GET_SYS_VAR_I(10)
	SYSINVAR11 = _GET_SYS_VAR_I(11)
	SYSINVAR12 = _GET_SYS_VAR_I(12)
	SYSINVAR13 = _GET_SYS_VAR_I(13)
	SYSINVAR14 = _GET_SYS_VAR_I(14)
	SYSINVAR15 = _GET_SYS_VAR_I(15)
	SYSINVAR16 = _GET_SYS_VAR_I(16)
	SYSINVAR17 = _GET_SYS_VAR_I(17)
	SYSINVAR18 = _GET_SYS_VAR_I(18)
	SYSINVAR19 = _GET_SYS_VAR_I(19)
end

-- @breif: setSysInVar
function SETSYSINVARI(id, value)
	return _SET_SYS_IN_VAR_I(id, value)
end

-- @breif: setSysOutVar and send 
function SENDSYSOUTVARI(index,value)
	if index > 10 then
		GOTOERROR("index 不能大于默认数组长度10")
		return
	end
	SYSOUTVAR[index] = value
	return _SET_SYS_OUT_VAR_I(index,value)
end

-- @breif: resetSysOutVar
function RESETSYSOUTVARI()
	return _RESET_SYS_OUT_VAR_I()
end

-- @breif: setSysInParaI
function GETSYSPARAMETERI(id)
	return _GET_SYS_PARAM_I(id)
end

-- @breif: setSysInParaD
function GETSYSPARAMETERF(id)
	return _GET_SYS_PARAM_F(id)
end

-- @breif: setLuaAppStatus
function SETLUAAPPSTATUS(status)
	return _SET_LUA_APP_STATUS(status)
end


-- @breif: calc X,Y,Z offsets of target position
-- XOffset:The displacement in the x-direction, in the object coordinate system
-- YOffset:The displacement in the y-direction, in the object coordinate system
-- ZOffset:The displacement in the z-direction, in the object coordinate system
function OFFS(p,XOffset,YOffset,ZOffset)
	local LP1=MFRAME(p._x+XOffset,p._y+YOffset,p._z+ZOffset,p._rx,p._ry,p._rz,p._ext1,p._ext2,p._ext3,p._ext4,p._ext5,p._ext6)
	return LP1
end

-- @brief: Offs is used to add an offset in the object coordinate system to a robot position,
-- XOffset:The displacement in the x-direction, in the object coordinate system
-- YOffset:The displacement in the y-direction, in the object coordinate system
-- ZOffset:The displacement in the z-direction, in the object coordinate system
function MOVLOFFS(p,XOffset,YOffset,ZOffset,speed,zone,tool,user)
	while 1 do
		local LP1 = OFFS(p,XOffset,YOffset,ZOffset)
		local ret = _MOVE_L(LP1,speed,zone,tool,user)
		if ret == 0 or ret == -1 then
			TIMER(10)
		else
			return 1
		end
	end
end

function COLLSUPVON()
	_COLL_SUPV_ON()
end

function COLLSUPVOFF()
	_COLL_SUPV_OFF()
end

-- @breif: calc X,Y,Z offsets and Rz rotation of target position
-- XOffset:The displacement in the x-direction, in the object coordinate system
-- YOffset:The displacement in the y-direction, in the object coordinate system
-- ZOffset:The displacement in the z-direction, in the object coordinate system
-- Rz:     The rotation in z-axis, in the object cordinate system
function OFFSWITHROTZ(p,XOffset,YOffset,ZOffset,Rz)
	local xTarget = p._x*COS(Rz)-p._y*SIN(Rz)+XOffset
	local yTarget = p._x*SIN(Rz)+p._y*COS(Rz)+YOffset
	local zTarget = p._z+ZOffset
	local zRot = p._rz+Rz
	if zRot > 180 then
		zRot = zRot-360
	elseif zRot <= -180 then
		zRot = zRot+360
	end
	local LP1=MFRAME(xTarget,yTarget,zTarget,p._rx,p._ry,zRot,p._ext1,p._ext2,p._ext3,p._ext4,p._ext5,p._ext6)
	return LP1
end

-- @brief: Offs is used to add an offset in the object coordinate system to a robot position,
-- XOffset:The displacement in the x-direction, in the object coordinate system
-- YOffset:The displacement in the y-direction, in the object coordinate system
-- ZOffset:The displacement in the z-direction, in the object coordinate system
-- Rz:     The rotation in z-axis, in the object cordinate system
function MOVLOFFSWITHROTZ(p,XOffset,YOffset,ZOffset,Rz,speed,zone,tool,user)
	while 1 do
		local LP1 = OFFSWITHROTZ(p,XOffset,YOffset,ZOffset,Rz)
		local ret = _MOVE_L(LP1,speed,zone,tool,user)
		if ret == 0 or ret == -1 then
			TIMER(10)
		else
			return 1
		end
	end
end

-- @brief: JOINTS4EQUAL is to check if two joint targets are close to each other within the allowed tolerance,
--          it will check J1-J4 value of each joint target
-- Jtarget1: Joint target 1
-- Jtarget2: Joint target 2
-- tol     : the allowed tolerance between the two joint targets.
-- todo: Unit of tol for both  Revolute Joint and Prismatic Joint are same. Maybe it should be adjusted.
function JOINTS4EQUAL(Jtarget1, Jtarget2, tol)
	if tol <= 0 then
		GOTOERROR("tolerance should be > 0")
		return
	else
		if (Jtarget1._j1-Jtarget2._j1 < tol and Jtarget1._j1-Jtarget2._j1 > -tol and Jtarget1._j2-Jtarget2._j2 < tol and Jtarget1._j2-Jtarget2._j2 > -tol and Jtarget1._j3-Jtarget2._j3 < tol and Jtarget1._j3-Jtarget2._j3 > -tol and Jtarget1._j4-Jtarget2._j4 < tol and Jtarget1._j4-Jtarget2._j4 > -tol) then
			return 1
		else
			return 0
		end
	end
end

-- @brief: JOINTS6EQUAL is to check if two joint targets are close to each other within the allowed tolerance,
--          it will check J1-J6 value of each joint target
-- Jtarget1: Joint target 1
-- Jtarget2: Joint target 2
-- tol     : the allowed tolerance between the two joint targets.
-- todo: Unit of tol for both  Revolute Joint and Prismatic Joint are same. Maybe it should be adjusted.
function JOINTS6EQUAL(Jtarget1, Jtarget2, tol)
	if tol <= 0 then
		GOTOERROR("tolerance should be > 0")
		return
	else
		if (Jtarget1._j1-Jtarget2._j1 < tol and Jtarget1._j1-Jtarget2._j1 > -tol and Jtarget1._j2-Jtarget2._j2 < tol and Jtarget1._j2-Jtarget2._j2 > -tol and Jtarget1._j3-Jtarget2._j3 < tol and Jtarget1._j3-Jtarget2._j3 > -tol and Jtarget1._j4-Jtarget2._j4 < tol and Jtarget1._j4-Jtarget2._j4 > -tol and Jtarget1._j5-Jtarget2._j5 < tol and Jtarget1._j5-Jtarget2._j5 > -tol and Jtarget1._j6-Jtarget2._j6 < tol and Jtarget1._j6-Jtarget2._j6 > -tol) then
			return 1
		else
			return 0
		end
	end
end

-- @brief: POSEEQUAL is to check if two pose targets are close to each other within the allowed tolerance,
-- P1 : pose target 1
-- P2 : pose target 2
-- tolT: the allowed trans tolerance between the two pose targets.
-- tolR: the allowed rot tolerance between the two pose targets.
function POSEEQUAL(P1, P2, tolT, tolR)
	if (tolT <= 0 or tolR <= 0) then
		GOTOERROR("tolerance should be > 0")
		return
	else
		if (P1._x-P2._x < tolT and P1._x-P2._x > -tolT and P1._y-P2._y < tolT and P1._y-P2._y > -tolT and P1._z-P2._z < tolT and P1._z-P2._z > -tolT and P1._rx-P2._rx < tolR and P1._rx-P2._rx > -tolR and P1._ry-P2._ry < tolR and P1._ry-P2._ry > -tolR and P1._rz-P2._rz < tolR and P1._rz-P2._rz > -tolR) then
			return 1
		else
			return 0
		end
	end
end

function SETEXTJTRQLIMIT(limit)
	_SET_EXTJ_TRQ_LIMIT(limit)
end

function MOVEXTJWITHFORCE(extj, spd, force)
	MOVFINISH()
	TIMER(100)
	SETEXTJTRQLIMIT(force)
	local LJointTarget = MJOINT(0,0,0,0,0,0,0,0,0,0,0,0)
	LJointTarget._ext1 = extj._a1
	LJointTarget._ext2 = extj._a2
	LJointTarget._ext3 = extj._a3
	LJointTarget._ext4 = extj._a4
	LJointTarget._ext5 = extj._a5
	LJointTarget._ext6 = extj._a6
	MOVEXTJ(LJointTarget, spd, 0, T0, U0)
end

function ENABLERECORDINS()
	MOVFINISH()
	_ENABLE_RECORD_INS()
	TIMER(100)
end

function DISABLERECORDINS()
	MOVFINISH()
	_DISABLE_RECORD_INS()
	TIMER(100)
end

--[[
["row：行"]：总行数
["col：列"]：总列数
["参考点1"]：最左下角的栈点
["参考点2"]：最右下角的栈点
["参考点3"]：最左上角的栈点
["参考点4"]：最右上角的栈点
]]
function STACKCONFIGURATION(row,col,refPoint1,refPoint2,refPoint3,refPoint4)
	if(type(row) ~= "number" or type(col) ~= "number") then  																		--[[检查排样规格]]
		GOTOERROR("row or col format is not valid")
		return nil
	end
	if(row <=0 or col <=0) then																										--[[检查排样规格数字]]
		GOTOERROR("row or col value is not valid")
		return nil
	end
	local stack = {}
	stack._totalRow = row
	stack._totalCol = col
	local xOffset = 0																												--[[x轴方向偏移量]]
	local yOffset = 0																												--[[y轴方向偏移量]]
	local zOffset = 0																												--[[z轴方向偏移量]]
	local rxOffset = 0																												--[[rx偏移量]]
	local ryOffset = 0																												--[[ry偏移量]]
	local rzOffset1 = 0																												--[[rz偏移量1]]
	local rzOffset2 = 0																												--[[rz偏移量2]]
	-- rzoffset1 = refPoint3._rz - refPoint2._rz
	-- if(rzoffset1 >= 1 or rzoffset1 <= -1) then																					--[[对角线计算rz姿态偏移]]
	-- 	GOTOERROR("rz offset is too much 1")
	-- 	return nil
	-- end
	-- rzoffset2 = refPoint4._rz - refPoint1._rz
	-- if(rzoffset2 >= 1 or rzoffset2 <= -1) then																					--[[对角线计算rz姿态偏移]]
	-- 	GOTOERROR("rz offset is too much 2")
	-- 	return nil
	-- end
	local pointNum = row*col																										--[[空间点数]]
	stack._totalpointNum = pointNum
	local index = 1																													--[[工作点集映射为工作编号]]
	stack.pointSet = {}																												--[[码垛工作点集]]
	for q=1, pointNum, 1 do
		stack.pointSet[q] = {}
	end
	stack.rowOffset = {}																											--[[行方向偏移量集]]
	stack.colOffset = {}																											--[[列方向偏移量集]]
	for m=1, 6, 1 do
		stack.rowOffset[m] = {}
		stack.colOffset[m] = {}
	end
	if(row ~=1) then																												--[[计算列间上偏移量]]
		stack.colOffset[1] = (refPoint3._x - refPoint1._x) / (row-1)
		stack.colOffset[2] = (refPoint3._y - refPoint1._y) / (row-1)
		stack.colOffset[3] = (refPoint3._z - refPoint1._z) / (row-1)
		stack.colOffset[4] = (refPoint3._rx - refPoint1._rx) / (row-1)
		stack.colOffset[5] = (refPoint3._ry - refPoint1._ry) / (row-1)
		stack.colOffset[6] = (refPoint3._rz - refPoint1._rz) / (row-1)
	else
		stack.colOffset[1] = 0
		stack.colOffset[2] = 0
		stack.colOffset[3] = 0
		stack.colOffset[4] = 0
		stack.colOffset[5] = 0
		stack.colOffset[6] = 0
	end
	if(col ~=1) then																												--[[计算行间上偏移量]]
		stack.rowOffset[1] = (refPoint2._x - refPoint1._x) / (col-1)
		stack.rowOffset[2] = (refPoint2._y - refPoint1._y) / (col-1)
		stack.rowOffset[3] = (refPoint2._z - refPoint1._z) / (col-1)
		stack.rowOffset[4] = (refPoint2._rx - refPoint1._rx) / (col-1)
		stack.rowOffset[5] = (refPoint2._ry - refPoint1._ry) / (col-1)
		stack.rowOffset[6] = (refPoint2._rz - refPoint1._rz) / (col-1)
	else
		stack.rowOffset[1] = 0
		stack.rowOffset[2] = 0
		stack.rowOffset[3] = 0
		stack.rowOffset[4] = 0
		stack.rowOffset[5] = 0
		stack.rowOffset[6] = 0
	end
	for i = 1, row, 1 do
		for j = 1, col, 1 do
			stack.pointSet[index]._x = refPoint1._x + ((j-1) * stack.rowOffset[1]) + ((i-1) * stack.colOffset[1])							--[[x偏移]]
			stack.pointSet[index]._y = refPoint1._y + ((j-1) * stack.rowOffset[2]) + ((i-1) * stack.colOffset[2])							--[[y偏移]]
			stack.pointSet[index]._z = refPoint1._z + ((j-1) * stack.rowOffset[3]) + ((i-1) * stack.colOffset[3])							--[[z偏移]]
			stack.pointSet[index]._rx = refPoint1._rx + ((j-1) * stack.rowOffset[4]) + ((i-1) * stack.colOffset[4])							--[[rx偏移]]
			stack.pointSet[index]._ry = refPoint1._ry + ((j-1) * stack.rowOffset[5]) + ((i-1) * stack.colOffset[5])							--[[ry偏移]]
			stack.pointSet[index]._rz = refPoint1._rz + ((j-1) * stack.rowOffset[6]) + ((i-1) * stack.colOffset[6])							--[[rz偏移]]
			index = index + 1
		end
	end
	return stack
end

--[[
	["堆栈表"]
	["行数"]:1
	["列数"]:1
]]
function GETSTACKTARGETPOINT(stack,row,col)
	if(type(stack) ~= "table" or stack == nil) then
		GOTOERROR("Stack is null")
		return
	end
	if(type(row) ~= "number" or type(col) ~="number") then
		GOTOERROR("row or col format is not valid")
		return nil
	end
	if(row <=0 or col <=0) then
		GOTOERROR("row or col value is not valid")
		return nil
	end
	if(row >stack._totalRow or col >stack._totalCol) then
		GOTOERROR("row or col value exceeds the allowed range")
		return nil
	end
	local index = ((row-1)*stack._totalCol) + col 	--[[点位映射至编号]]
	local targetPos = MFRAME(stack.pointSet[index]._x,stack.pointSet[index]._y,stack.pointSet[index]._z,stack.pointSet[index]._rx,stack.pointSet[index]._ry,stack.pointSet[index]._rz,0,0,0,0,0,0)
	return targetPos
end

-- @brief: GRIPPERDROPDET is to detect if gripper fail to grasp the item, that is, gripper is empty.
-- idx : to indicate which ext joint is used as gripper
-- trqtol: the allowed torque/force tolerance for gripper empty detection.
-- distol: the allowed distance/force tolerance for gripper empty detection.
-- return value: 1: gripper is holding the item; 2: gripper is empty
function GRIPPEREMPTYDET(idx, trqtol, distol)
	if (trqtol <= 0 or distol <= 0 ) then
		GOTOERROR("tolerance should be > 0")
		return
	else
		local torj = GETJOINTSNORMTRQ()
		local disj = GETJOINTS()
		local refdisj = GETREFJOINTS()
		if (idx == 1) then
			local err = disj._ext1 - refdisj._ext1
			local disjErr = math.abs(err)
			if ((torj._ext1 >= trqtol and disjErr >= distol ) or (torj._ext1 <= -trqtol and disjErr >= distol )) then
				return 1
			else
				return 2
			end
		elseif (idx == 2) then
			local err = disj._ext2 - refdisj._ext2
			local disjErr = math.abs(err)
			if ((torj._ext2 >= trqtol and disjErr >= distol ) or (torj._ext2 <= -trqtol and disjErr >= distol )) then
				return 1
			else
				return 2
			end
		else
			GOTOERROR("invalid index for ext joint")
			return
		end
	end
end

function GETGRAVITY(tallPoint,lowPoint,numPoints)
	if(tallPoint == lowPoint or numPoints <=0) then
		GOTOERROR("Parameter is not vaild")
		return
	else
		local highErr = tallPoint._j2 - lowPoint._j2			--计算高度差
		local errOffset = highErr/(numPoints-1)					--计算高度偏差
		local uptarPoint = lowPoint								--向上移动目标点
		local downPoint = tallPoint								--向下移动目标点
		local startPoint = lowPoint                             --记录起点
		local torJ1,torJ2										--力
		local torJ1Sum = 0
		local torJ2Sum = 0
		local minVal = lowPoint._j2								--转存最低高度值
		local maxVal = tallPoint._j2							--转存最高高度值
		local VAR1 = 0
		local VAR2 = 0
		MOVABSJ(lowPoint,100,0)									--回到初始最低点
		TIMER(1000)
		for i=1,(numPoints-1),1 do
			PRINT(i)
			for j=1,10,1 do
				uptarPoint._j2 = minVal + (errOffset*i)				--目标点值   
				if(uptarPoint._j2 >= maxVal) then					--防撞判断
					return
				end
				downPoint._j2 = minVal + (errOffset*(i+1))
				if(downPoint._j2 >= maxVal) then					--防撞判断
					downPoint._j2 = maxVal - 20						--防止二轴撞击
				end
				MOVABSJ(uptarPoint,100,0)						--由下至上去到目标点
				MOVFINISH()
				TIMER(5000)
				torJ1 = GETJOINTSTRQ()							--获取第一次值
				torJ1Sum = torJ1Sum + torJ1._j2
				MOVABSJ(downPoint,100,0)							--去到目标点的下一点
				MOVFINISH()
				MOVABSJ(uptarPoint,100,0)						--由上至下回到目标点
				MOVFINISH()
				TIMER(5000)
				torJ2 = GETJOINTSTRQ()							--获取第二次值
				torJ2Sum = torJ2Sum + torJ2._j2
				startPoint._j2 = minVal+ (errOffset*(i-1))
				MOVABSJ(startPoint,100,0)
				MOVFINISH()
			end
			VAR1 = ((torJ1Sum/10) + (torJ2Sum/10))/2
			VAR2 = ((torJ1Sum/10) - (torJ2Sum/10))/2
			PRINT(VAR1)
			PRINT(VAR2)
			torJ1Sum = 0
			torJ2Sum = 0
		end
	end
end

-- @brief: Initialize generation of stack data
-- objId : Material ID
-- stackHeight: Stacking height of materials
-- offsetHeight: Offset height of material
-- return value: stack table
function STACK2CONFIGURATION(objId,stackHeight,offsetHeight)
	if(type(objId) ~= "number" or type(stackHeight) ~= "number" or type(offsetHeight) ~= "number") then
		GOTOERROR("Parameters format is not valid")
		return nil
	end
	if(objId <0 or stackHeight <0 or offsetHeight <0) then
		GOTOERROR("Parameters value is not valid")
		return nil
	end
	local stack = {}
	stack.objId = objId
	stack.stackHeight = stackHeight
	stack.offsetHeight = offsetHeight
	return stack
end
-- @brief: Calculate target points
-- stack : stack table
-- pointIndex: where in row(posX)
-- lowestPoint: lowest pos in column
-- offsetX: x axis offset value (default:0) on stack point
-- offsetY: y axis offset value (default:0) on stack point
-- return value: targe pos point info
function GETSTACK2TARGETPOINT(stack,pointIndex,lowestPoint,offsetX,offsetY)
	if(type(stack) ~= "table" or type(pointIndex) ~= "number" or type(offsetX) ~= "number" or type(offsetY) ~= "number")then
		GOTOERROR("Parameters format is not valid")
	end
	if(pointIndex < 0)then
		GOTOERROR("pointIndex value is not valid")
	end
		local tarPoint = {}
		tarPoint._x = lowestPoint._x + (offsetX)
		tarPoint._y = lowestPoint._y + (offsetY)
		tarPoint._z = lowestPoint._z + ((pointIndex-1)*stack.stackHeight+stack.offsetHeight)
		tarPoint._rx = lowestPoint._rx
		tarPoint._ry = lowestPoint._ry
		tarPoint._rz = lowestPoint._rz
	local targetPos = MFRAME(tarPoint._x,tarPoint._y,tarPoint._z,tarPoint._rx,tarPoint._ry,tarPoint._rz,0,0,0,0,0,0)
	return targetPos
end

function GETSTACK2GROUP()
	local id,stackHeinght,offsetHeight
	for i=0,9,1 do
		id = GETSYSPARAMETERI(i)
		offsetHeight = GETSYSPARAMETERF(3*i)
		stackHeinght = GETSYSPARAMETERF(3*i+1)
		StackGroup[i+1] = STACK2CONFIGURATION(id,stackHeinght,offsetHeight)
	end
end

function SEARCHINSTACK2GROUP(objId)
	for i=1,10,1 do
		if StackGroup[i].objId==objId then
			return i
		end
	end
	return nil
end


--liquid data definition
function MLTARGET(slotLoc, colNo, rowNo)
	return _DEF_LIQ_TARGET(slotLoc, colNo, rowNo)
end

function MLCONPARA(volume, speed, zLoc, mixType, delayTime, zLiqLevel, liqLevelDet, liqLevelFollow)
	return _DEF_LIQ_CON_PARA(volume, speed, zLoc, mixType, delayTime, zLiqLevel, liqLevelDet, liqLevelFollow)
end

function MLTCHPARA(speed, zLoc, inHoleLoc, opTime)
	return _DEF_LIQ_TCH_PARA(speed, zLoc, inHoleLoc, opTime)
end

function MLAGAPPARA(volume, speed, zLoc)
	return _DEF_LIQ_AIRGAP_PARA(volume, speed, zLoc)
end

function MLS32ARRAY(data1, data2, data3, data4, data5,
				data6, data7, data8, data9, data10)
	return _DEF_LIQ_S32_ARRAY(data1, data2, data3, data4, data5,
				data6, data7, data8, data9, data10)
end

function MLLYTINFO(modSlotLoc, modTypeId)
	return _DEF_LIQ_LAYOUT_INFO(modSlotLoc, modTypeId)
end

function MLMODINSD(data1, data2, data3, data4, data5)
	return _DEF_LIQ_MOD_INS_DATA(data1, data2, data3, data4, data5)
end

function MLJOBDATA(data1, data2, data3, data4, data5, data6, data7, data8, data9, data10,
					data11, data12, data13, data14, data15, data16, data17, data18, data19, data20, 
                    data21, data22, data23, data24, data25, data26, data27, data28, data29, data30)
	return _DEF_LIQ_JOB_DATA(data1, data2, data3, data4, data5, data6, data7, data8, data9, data10,
					data11, data12, data13, data14, data15, data16, data17, data18, data19, data20, 
                    data21, data22, data23, data24, data25, data26, data27, data28, data29, data30)
end

function MLJOBREF(jobName, jobData)
	return _DEF_LIQ_JOB_REF(jobName, jobData)
end

function MLJOBFBK(jobName, jobRet)
	return _DEF_LIQ_JOB_FBK(jobName, jobRet)
end


-- liquid related command Enum 
local EnumLiquidCmd = {
    LM_INST_NONE = 0,
	
	LM_INST_HS_MOD_GET_ERR_CODE = 0x00070002,
	LM_INST_HS_LATCH_OPEN = 0x00070003,
	LM_INST_HS_LATCH_CLOSE = 0x00070004,
	LM_INST_HS_LATCH_GET_STA = 0x00070005,
	LM_INST_HS_SHAKER_START = 0x00070006,
	LM_INST_HS_SHAKER_GET_SPD = 0x00070007,
	LM_INST_HS_SHAKER_STOP = 0x00070009,
	LM_INST_HS_HEATER_START = 0x0007000A,
	LM_INST_HS_HEATER_GET_TEMP = 0x0007000B,
	LM_INST_HS_HEATER_GET_STA = 0x0007000D,
	LM_INST_HS_HEATER_STOP = 0x0007000E,
	LM_INST_HS_SHAKER_GET_STA = 0x0007000F,
	LM_INST_HS_GET_STA = 0x00070010,
	LM_INST_HS_KEEP_SHAKE_TIME = 0x00070011,

	LM_INST_PIPT_GET_STA = 0x00060005,
	LM_INST_PIPT_SET_DET = 0x0006000E,

	LM_INST_POSPRESS_RESET = 0x00080004,
	LM_INST_POSPRESS_MOD_GET_STA = 0x00080002,
	LM_INST_POSPRESS_GET_ERR_CODE = 0x00080006,
	LM_INST_POSPRESS_INFLATE = 0x00080003,
	LM_INST_POSPRESS_PUSH_DOWN = 0x00080005,

	LM_INST_PCR_GET_STA = 0x000B0002,
	LM_INST_PCR_GET_SOFT_ERROR = 0x000B0003,
	LM_INST_PCR_GET_DEV_ERROR = 0x000B0004,
	LM_INST_PCR_CONTROL_COVER = 0x000B0005,
	LM_INST_PCR_CONTROL_PROG_STA = 0x000B0006,
	LM_INST_PCR_SELECT_PROG_EXECUTE = 0x000B0007,
	LM_INST_PCR_READ_PROG_LIST = 0x000B0008,
}

local EnumPipetteStatus = {
	PIPETTE_IDLE = 1,
	PIPETTE_BUSY = 2,
	PIPETTE_ERROR = 3,
}

local EnumLatchStatus = {
	LATCH_MOVING = 0,
	LATCH_CLAMPED = 1,
	LATCH_LOOSE = 2,
	LATCH_ERROR = 3,
}

local EnumHeaterStatus = {
	HEATER_IDLE = 0,
	HEATER_WORKING = 1,
	HEATER_ERROR = 2,
}

local EnumShakerStatus = {
	SHAKER_IDLE = 0,
	SHAKER_BUSY = 1,
	SHAKER_ERROR = 2,
}

local EnumHSDevStatus = {
	HSDEV_IDLE = 1,
	HSDEV_BUSY = 2,
	HSDEV_ERROR = 3,
}

local EnumPosPressStatus = {
	POSPRESS_IDLE = 1,
	POSPRESS_RUNNING = 2,
	POSPRESS_ERROR = 3,
}

local EnumPCRStatus = {
	PCR_IDLE = 1,
	PCR_BUSY = 2,
	PCR_ERROR = 3,
}

--liquid delay time
local EnumDelayValue = {
	DEFAULT = 10,   --don't modify
	COMMON = 100,
	MIDDLE = 200,
	USUAL = 500,
	GETSTATUS = 100,
	HIGH = 1000,
	HUGE = 2000,
}

EnumMixType = {
	NO_MIX = 0,
	MIX_BEFORE_OP = 1,
	MIX_AFTER_OP = 2,
	MIX_BOTH = 3
}

local EnumToolType = {
	LIQTOOL_TYPE_PIPETTE_LEFT = 1,
	LIQTOOL_TYPE_PIPETTE_RIGHT = 2,
	LIQTOOL_TYPE_GRIPPER = 3
}

--liquid related command
function LIQ_LOADMOD(moduleFile)
	local ret = _LIQ_LOAD_MOD(moduleFile)
	if ret == 0 then
		GOTOERROR("error in LIQ_LOADMOD")
	else
		return 1
	end
end

function LIQ_LOADSAMPLE(sampleFile)
	local ret = _LIQ_LOAD_SAMPLE(sampleFile)
	if ret == 0 then
		GOTOERROR("error in LIQ_LOADSAMPLE")
	else
		return 1
	end
end

function LIQ_LOADTIP(tipFile)
	local ret = _LIQ_LOAD_TIPRACK(tipFile)
	if ret == 0 then
		GOTOERROR("error in LIQ_LOADTIP")
	else
		return 1
	end
end

function LIQ_LOADLAYOUT(layoutFile)
	return _LIQ_LOAD_LAYOUT(layoutFile)
end

function LIQ_GETLAYOUT()
	return _LIQ_GET_LAYOUT()
end

function LIQCMDFINISH()
	while 1 do
		local ret = _LIQ_IS_CMD_FINISH()
		if ret == 0 then
			TIMER(10)
		else
			return
		end
	end
end

function SETLIQSYSERR()
	_LIQ_SET_SYS_ERR()
end

function LIQ_GET_PIPT_STATUS(pipetId)
	local status = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	status = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_PIPT_GET_STA,pipetId)
	return status.a1
end

function LIQ_CHECKBFPICKTIP(typeName, tipCnt, ...)
	local tipRackTypeId = -1

	local args = {...}
	if #args >= 1 then
		if type(args[1]) == "number" then
			tipRackTypeId = args[1]
		end
	end

	local retValue = _LIQ_CHECK_BF_PICK_TIP(typeName, tipCnt, tipRackTypeId)
	if retValue.ret == 0 then
		GOTOERROR("error in LIQ_CHECKBFPICKTIP")
		return
	end
	return retValue.isAvailable, retValue.tipCnts
end

function LIQ_PICKUPTIP(pipetId, typeName, tipCnt, ...)
	local tipRackTypeId = -1

	local args = {...}
	if #args >= 1 then
		if type(args[1]) == "number" then
			tipRackTypeId = args[1]
		end
	end

	while 1 do
		local ret = _LIQ_PICK_TIP(pipetId, typeName, tipCnt, tipRackTypeId)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_PICKUPTIP")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd pick tip is finished")
end

function LIQ_PICKUPREUTIP(pipetId, typeName, col, row, tipCnt, ...)
	local slotLoc = -1

	local args = {...}
	if #args >= 1 then
		if type(args[1]) == "number" then
			slotLoc = args[1]
		end
	end

	while 1 do
		local ret = _LIQ_PICK_REU_TIP(pipetId, typeName, col, row, tipCnt, slotLoc)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_PICKUPREUTIP")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd pick reu tip is finished")
end

function LIQ_DROPTIP(pipetId, ...)
	local args = {...}
    local toZPosType = 1
    if #args >= 1 then
		if type(args[1]) == "number" then
        	toZPosType = args[1]
		else
			GOTOERROR("droptip 2nd parameter must be a number")
			return
		end
    end

	while 1 do
		local modStatus = LIQ_GET_PIPT_STATUS(pipetId)
		if modStatus == EnumPipetteStatus.PIPETTE_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	while 1 do
		local ret = _LIQ_DROP_TIP(pipetId, 0, toZPosType)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_DROPTIP")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd drop tip is finished")
end

function LIQ_DROPTIPBYTYPE(pipetId, tipTypeId)
	local toZPosType = 1
	PRINT("get pipt status before drop tip by type")
	while 1 do
		local modStatus = LIQ_GET_PIPT_STATUS(pipetId)
		if modStatus == EnumPipetteStatus.PIPETTE_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	PRINT("start drop tip by type")
	while 1 do
		local ret = _LIQ_DROP_TIP(pipetId, tipTypeId, toZPosType)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_DROPTIPBYTYPE")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd drop tip by type is finished")
end

function LIQ_RETTIP(pipetId)
	while 1 do
		local modStatus = LIQ_GET_PIPT_STATUS(pipetId)
		if modStatus == EnumPipetteStatus.PIPETTE_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	while 1 do
		local ret = _LIQ_RET_TIP(pipetId)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_RETTIP")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd return tip is finished")
end

function LIQ_TOUCHTIP(pipetId, target, touchPara)
	while 1 do
		local ret = _LIQ_TOUCH_TIP(pipetId, target, touchPara)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_TOUCHTIP")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd touch tip is finished")
end

function LIQ_ASPIRATE(pipetId, target, conPara, ...)
	local args = {...}
    local toZPosType = 1
	local enAntiDrip = 0
    if #args >= 1 then
		if type(args[1]) == "number" then
			toZPosType = args[1]
		end
		if type(args[2]) == "number" then
			enAntiDrip = args[2]
		end
    end

	if conPara.speed <=0 or conPara.volume <=0 then
		GOTOERROR("aspirate parameter must be greater than 0")
		return
	end
	while 1 do
		local modStatus = LIQ_GET_PIPT_STATUS(pipetId)
		if modStatus == EnumPipetteStatus.PIPETTE_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	while 1 do
		local ret = _LIQ_ASPIRATE(pipetId, target, conPara, toZPosType, enAntiDrip)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_ASPIRATE")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd asp is finished")
end

function LIQ_DISPENSE(pipetId, target, conPara, ...)
	local args = {...}
    local toZPosType = 1
	local enAntiDrip = 0
    if #args >= 1 then
		if type(args[1]) == "number" then
			toZPosType = args[1]
		end
		if type(args[2]) == "number" then
			enAntiDrip = args[2]
		end
    end

	if conPara.speed <=0 or conPara.volume <=0 then
		GOTOERROR("dispense parameter must be greater than 0")
		return
	end
	while 1 do
		local modStatus = LIQ_GET_PIPT_STATUS(pipetId)
		if modStatus == EnumPipetteStatus.PIPETTE_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	while 1 do
		local ret = _LIQ_DISPENSE(pipetId, target, conPara, toZPosType, enAntiDrip)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_DISPENSE")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd disp is finished")
end

function LIQ_BLOWOUT(pipetId, target, volume, zLoc, speed, toZPosType, pathType)
	-- toZPosType 1:to zhome position, 2:to labware top position, 3:to current position
	-- pathType 1:specfic blowout path after dispensing 0:default 
	if speed <= 0 then
		GOTOERROR("blow out speed parameter must be greater than 0")
		return
	end

	while 1 do
		local modStatus = LIQ_GET_PIPT_STATUS(pipetId)
		if modStatus == EnumPipetteStatus.PIPETTE_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end

	while 1 do
		local ret = _LIQ_BLOWOUT(pipetId, target, volume, zLoc, speed, toZPosType, pathType)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_BLOWOUT")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd blow out is finished")
end

function LIQ_AIRGAPHD(pipetId, target, airGapPara, ...)
	local args = {...}
    local toZPosType = 1
    if #args >= 1 then
		if type(args[1]) == "number" then
        	toZPosType = args[1]
		else
			GOTOERROR("airgaphd fourth parameter must be a number")
			return
		end
    end

	if airGapPara.speed <=0 or airGapPara.volume <=0 then
		GOTOERROR("airgaphd parameter must be greater than 0")
		return
	end
	while 1 do
		local modStatus = LIQ_GET_PIPT_STATUS(pipetId)
		if modStatus == EnumPipetteStatus.PIPETTE_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end

	LIQ_DISABLEPIPTALARMDET(pipetId)
	while 1 do
		local ret = _LIQ_AIRGAP_HEAD(pipetId, target, airGapPara, toZPosType)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_AIRGAPHD")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd air gap head is finished")
	LIQ_RESUMEPIPTALARMDET(pipetId)
end

function LIQ_AIRGAPTL(pipetId, target, airGapPara, ...)
	local args = {...}
    local toZPosType = 1
	local enAntiDrip = 0
    if #args >= 1 then
		if type(args[1]) == "number" then
			toZPosType = args[1]
		end
		if type(args[2]) == "number" then
			enAntiDrip = args[2]
		end
    end

	if airGapPara.speed <=0 or airGapPara.volume <=0 then
		GOTOERROR("airgaptl parameter must be greater than 0")
		return
	end
	while 1 do
		local modStatus = LIQ_GET_PIPT_STATUS(pipetId)
		if modStatus == EnumPipetteStatus.PIPETTE_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end

	LIQ_DISABLEPIPTALARMDET(pipetId)
	while 1 do
		local ret = _LIQ_AIRGAP_TAIL(pipetId, target, airGapPara, toZPosType, enAntiDrip)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_AIRGAPTL")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd air gap tail is finished")
	LIQ_RESUMEPIPTALARMDET(pipetId)
end

function LIQ_HMPIPET(pipetId)
	while 1 do
		local modStatus = LIQ_GET_PIPT_STATUS(pipetId)
		if modStatus == EnumPipetteStatus.PIPETTE_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	while 1 do
		local ret = _LIQ_HOME_PIPT(pipetId)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_HMPIPET")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd home pipt is finished")
end

function LIQ_PIPETZHOME(pipetId)
	while 1 do
		local ret = _LIQ_PIPT_ZHOME(pipetId)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_PIPETZHOME")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd pipt to zhome is finished")
end

function LIQ_HMGRIPPER()
	while 1 do
		local ret = _LIQ_HOME_GRIPPER()
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_HMGRIPPER")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd home gripper is finished")
end

function LIQ_HMGANTRY()
	while 1 do
		local ret = _LIQ_HOME_GANTRY()
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_HMGANTRY")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd home gantry is finished")
end

function LIQ_MOVE(orgin, target, isHolding, pickLayer)
	while 1 do
		local ret = _LIQ_MOVE_LABW(orgin, target, isHolding, pickLayer)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_MOVE")
			return
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd move labware is finished")
end

function LIQ_MOD_SETGET(cmdId, modId, inData)
	local ret = 0
	local outData = MLMODINSD(0.000, 0.000, 0.000, 0.000, 0.000)
	local isGetCmd = 0
	while 1 do
		ret, outData = _LIQ_MOD_SET_AND_GET(cmdId, modId, inData, isGetCmd)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		elseif ret == -1 then
			GOTOERROR("error in LIQ_MOD_SET")
			return
		else
			return 1
		end
	end
end

function LIQ_MOD_SET(cmdId, modId, inData)
	local ret = 0
	while 1 do
		ret = _LIQ_MOD_SET(cmdId, modId, inData)
		if ret == 0 or ret == -1 then
			TIMER(EnumDelayValue.DEFAULT)
		else
			break
		end
	end
	LIQCMDFINISH()
	PRINT("cmd mod set is finished")
end

function LIQ_MOD_GET(cmdId, modId)
	local ret = 0
	local seqNo = 0
	local inData = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	local outData = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	while 1 do
		ret, seqNo = _LIQ_MOD_SET_REF(cmdId, modId, inData)
		if ret == 0 or ret == -1 then
			TIMER(EnumDelayValue.DEFAULT)
		else
			break
		end
	end
	while 1 do
		ret, outData = _LIQ_MOD_GET_FBK(seqNo)
		if ret == 0 or ret == -1 then
			TIMER(EnumDelayValue.DEFAULT)
		else
			return outData
		end
	end
end


function LIQ_GETJOBREF()
	return _LIQ_GET_JOB_REF()
end

function LIQ_SETJOBFBK(jobFbk)
	while 1 do
		local ret = _LIQ_SET_JOB_FBK(jobFbk)
		if ret == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		else
			return 1
		end
	end
end

function LIQ_GETSAMPINFO(typeId)
	local retValue = _LIQ_GET_SAMP_INFO(typeId)
	if retValue.ret == 0 or retValue.cnt == 0 then
		GOTOERROR("sample info data is invalid")
		return
	end
	return retValue.cnt, retValue.sampCol
end

function LIQ_GETSAMPCOLCNT(typeId)
	local retValue = _LIQ_GET_SAMP_COL_CNT(typeId)
	if retValue.ret == 0 then
		GOTOERROR("error in LIQ_GETSAMPCOLCNT")
		return
	end
	return retValue.colCnt
end

function LIQ_GETSAMPINFOBYPT(typeId)
	local retValue = _LIQ_GET_SAMP_INFO_BY_PATTERN(typeId)
	if retValue.ret == 0 then
		GOTOERROR("error in LIQ_GETSAMPINFOBYPT")
		return
	end
	return retValue.typeCnt, retValue.data
end

function LIQ_GETCOLSAMPINFO(typeId, colIdx)
	local retValue = _LIQ_GET_COL_SAMP_INFO(typeId, colIdx)
	if retValue.ret == 0 then
		GOTOERROR("error in LIQ_GETCOLSAMPINFO")
		return
	end
	return retValue.cnt, retValue.colSampInfo
end

function LIQ_GETRACKTIPSTAT(typeName, ...)
	local retValue, isUsed, typeId
	typeId = -1

	local args = {...}
	if #args >= 1 then
		if type(args[1]) == "number" then
			typeId = args[1]
		end
	end

	retValue, isUsed = _LIQ_GET_RACK_TIP_STATUS(typeName, typeId)
	if retValue == 0 then
		GOTOERROR("failed to get tip status in the rack")
		return
	end
	return isUsed
end

--heatshake command
function LIQ_HEATER_GET_MODSTATUS(modId)
	local status = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	status = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_HEATER_GET_STA,modId)
	if status~= nil then
		return status.a1
	end
end

function LIQ_LATCH_GET_MODSTATUS(modId)
	local status = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	status = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_LATCH_GET_STA,modId)
	if status~= nil then
		return status.a1
	end
end

function LIQ_SHAKER_GET_MODSTATUS(modId)
	local status = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	status = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_SHAKER_GET_STA,modId)
	if status~= nil then
		return status.a1
	end
end

function LIQ_HEATERDEV_GET_MODSTATUS(modId)
	local status = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	status = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_GET_STA,modId)
	if status~= nil then
		return status.a1
	end
end

function LIQ_OPEN_LATCH(modId)
	local inData = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	local retry = 3
	PRINT("start to open latch")
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_LATCH_OPEN,modId,inData)
	TIMER(EnumDelayValue.HUGE)
	while 1 do
		local latchStatus = LIQ_LATCH_GET_MODSTATUS(modId)
		if latchStatus == EnumLatchStatus.LATCH_LOOSE then
			PRINT("open latch done")
			break
		elseif latchStatus == EnumLatchStatus.LATCH_CLAMPED then
			LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_LATCH_OPEN, modId, inData)
			if retry > 0 then
				PRINT("still clamped, retry open latch")
				retry = retry - 1
				TIMER(EnumDelayValue.HUGE)
			else
				PRINT("still clamped, retry count used up, open latch failed")
				SETLIQSYSERR()
			end
		elseif latchStatus == EnumLatchStatus.LATCH_ERROR then
			PRINT("error, open latch failed")
			SETLIQSYSERR()
		end
		TIMER(EnumDelayValue.GETSTATUS)
	end
end

function LIQ_CLOSE_LATCH(modId)
	local inData = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	local retry = 3
	PRINT("start to close latch")
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_LATCH_CLOSE,modId,inData)
	TIMER(EnumDelayValue.HUGE)
	while 1 do
		local latchStatus = LIQ_LATCH_GET_MODSTATUS(modId)
		if latchStatus == EnumLatchStatus.LATCH_CLAMPED then
			PRINT("close latch done")
			break
		elseif latchStatus == EnumLatchStatus.LATCH_LOOSE then
			LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_LATCH_CLOSE, modId, inData)
			if retry > 0 then
				PRINT("still clamped, retry close latch")
				retry = retry - 1
				TIMER(EnumDelayValue.HUGE)
			else
				PRINT("still loose, retry count used up, close latch failed")
				SETLIQSYSERR()
			end
		elseif latchStatus == EnumLatchStatus.LATCH_ERROR then
			PRINT("error, close latch failed")
			SETLIQSYSERR()
		end
		TIMER(EnumDelayValue.GETSTATUS)
	end
end

function LIQ_START_SHAKE(modId,shakeRate,shakeDir)
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	if shakeRate > 0 then
		if shakeDir == 1 or shakeDir == 0 then
			cmdPara.a1= shakeRate
			cmdPara.a2 = shakeDir
			LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_SHAKER_START,modId,cmdPara)
		else
			GOTOERROR("shakeDir value is not vaild")
			return
		end
	else
		GOTOERROR("shakeRate value is not vaild")
		return
	end
	TIMER(EnumDelayValue.USUAL)
end

function LIQ_START_SHAKE_WIHOUT_LATCH(modId,shakeRate,shakeTime,shakeDir)
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	if shakeRate > 0 then
		if shakeDir == 1 or shakeDir == 0 then
			cmdPara.a1= shakeRate
			cmdPara.a2 = shakeDir
			cmdPara.a3 = shakeTime/1000
			LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_KEEP_SHAKE_TIME,modId,cmdPara)
		else
			GOTOERROR("shakeDir value is not vaild")
			return
		end
	else
		GOTOERROR("shakeRate value is not vaild")
		return
	end
	TIMER(EnumDelayValue.USUAL)
end

function LIQ_STOP_SHAKE(modId)
	local inData = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_SHAKER_STOP,modId,inData)
	TIMER(EnumDelayValue.USUAL)
end

function LIQ_SET_AND_WAIT_FOR_SHAKE(modId,shakeRate,shakeTime,shakeDir)
	PRINT("start to shake for a period")
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	if type(shakeRate) ~= "number" then
		GOTOERROR("shakeRate type is not vaild")
		return
	end
	if type(shakeTime) ~= "number" then
		GOTOERROR("shakeTime type is not vaild")
		return
	end
	if type(shakeDir) ~= "number" then
		GOTOERROR("shakeTime type is not vaild")
		return
	end
	while 1 do
		local latchStatus = LIQ_LATCH_GET_MODSTATUS(modId)
		if latchStatus ==  EnumLatchStatus.LATCH_CLAMPED then
			break
		elseif latchStatus == EnumLatchStatus.LATCH_LOOSE then
			LIQ_CLOSE_LATCH(modId)
			break
		elseif latchStatus == EnumLatchStatus.LATCH_MOVING then 
			TIMER(EnumDelayValue.GETSTATUS)
		else
			return
		end
	end
	if shakeRate>=200 and shakeRate <=3000 then
		if shakeDir == 1 or shakeDir == 0 then
			cmdPara.a1= shakeRate
			cmdPara.a2 = shakeDir
			LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_SHAKER_START,modId,cmdPara)
			TIMER(shakeTime)
			LIQ_STOP_SHAKE(modId)
		else
			GOTOERROR("shakeDir value is not vaild")
			return
		end
	else
		GOTOERROR("shakeRate value is not vaild")
		return
	end
	TIMER(EnumDelayValue.HUGE)
	while 1 do
		local latchStatus = LIQ_LATCH_GET_MODSTATUS(modId)
		if latchStatus == EnumLatchStatus.LATCH_MOVING then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	TIMER(EnumDelayValue.HUGE)
	PRINT("shake for a period done")
end

function LIQ_SET_TARGET_TEMP_AND_START(modId,tarTemp)
	if type(tarTemp) ~= "number" then
		GOTOERROR("tarTemp type is not vaild")
		return
	end
	if tarTemp>0 then
		local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
		cmdPara.a1 = tarTemp
		LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_HEATER_START,modId,cmdPara)
	else
		GOTOERROR("tarTemp value is not vaild")
		return
	end
end

function LIQ_SET_AND_WAIT_FOR_SHAKE_WITHOUT_LATCH(modId,shakeRate,shakeTime,shakeDir)
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	if type(shakeRate) ~= "number" then
		GOTOERROR("shakeRate type is not vaild")
		return
	end
	if type(shakeTime) ~= "number" then
		GOTOERROR("shakeTime type is not vaild")
		return
	end
	if type(shakeDir) ~= "number" then
		GOTOERROR("shakeTime type is not vaild")
		return
	end
	LIQ_START_SHAKE_WIHOUT_LATCH(modId,shakeRate,shakeTime,shakeDir)
	while 1 do
		local hsStatus = LIQ_SHAKER_GET_MODSTATUS(modId)
		if hsStatus == EnumShakerStatus.SHAKER_BUSY then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	TIMER(EnumDelayValue.HIGH)
end

function LIQ_STOP_HEATING(modId)
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_HEATER_STOP,modId,cmdPara)
	TIMER(EnumDelayValue.USUAL)
end

function LIQ_SET_AND_WAIT_FOR_TEMP(modId,timeOut,tarTemp)
	if type(timeOut) ~= "number"then
		GOTOERROR("timeOut type is not vaild")
		return
	end
	if type(tarTemp) ~= "number"then
		GOTOERROR("tarTemp type is not vaild")
		return
	end
	if timeOut < 0 then
		GOTOERROR("timeOut value is not vaild")
		return
	end
	local getData = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	local realTemp = 0
	local isArrive = 0
	local err = 0
	local startTime = 0
	local time = 0
	startTime = _GET_TIME_MS()
	LIQ_SET_TARGET_TEMP_AND_START(modId,tarTemp)
	while 1 do
		getData = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_HEATER_GET_TEMP,modId)
		if getData~=nil then
			realTemp = getData.a1
		end
		err = math.abs(realTemp - tarTemp)
		if err<0.5 then
			isArrive = 1
			break
		else
			time = _GET_TIME_MS()
			if (time - startTime)> timeOut then
				break
			else
				TIMER(EnumDelayValue.MIDDLE)
			end
		end
	end
	return isArrive
end

function LIQ_GET_SHAKE_HEATER_MOD_STATUS(modId)
	local getData = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	local shakeStatus = 0
	local heaterStatus = 0
	local shakeSpeed = 0
	local realTemp = 0
	getData = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_SHAKER_GET_SPD,modId)
	if getData~=nil then
		shakeSpeed = getData.a1
	end
	getData = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_HEATER_GET_TEMP,modId)
	if getData~=nil then
		realTemp = getData.a1
	end
	getData = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_LATCH_GET_STA,modId)
	if getData~=nil then
		shakeStatus = getData.a1
	end
	getData = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_HEATER_GET_STA,modId)
	if getData~=nil then
		heaterStatus = getData.a1
	end
	if shakeStatus == EnumLatchStatus.LATCH_MOVING or shakeStatus == EnumLatchStatus.LATCH_CLAMPED  then
		shakeStatus = 1
	else
		shakeStatus = 0
	end
	if heaterStatus == EnumHeaterStatus.HEATER_WORKING then
		heaterStatus = 1
	else
		heaterStatus = 0
	end
	return shakeStatus,shakeSpeed,heaterStatus,realTemp
end

--pospress command
function LIQ_POSPRESS_GET_MODSTATUS(modId)
	local status = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	status = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_POSPRESS_MOD_GET_STA,modId)
	if status~=nil then
		return status.a1
	end
end

function LIQ_POSPRESS_RESET(modId)
	PRINT("start to reset pos-press")
	local modStatus = -1
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	while 1 do
		modStatus = LIQ_POSPRESS_GET_MODSTATUS(modId)
		if modStatus == EnumPosPressStatus.POSPRESS_IDLE then
			LIQ_MOD_SET(EnumLiquidCmd.LM_INST_POSPRESS_RESET,modId,cmdPara)
			break
		elseif modStatus == EnumPosPressStatus.POSPRESS_ERROR then
			break
		else
			TIMER(EnumDelayValue.GETSTATUS)
		end
	end
	TIMER(EnumDelayValue.HUGE)
	while 1 do
		modStatus = LIQ_POSPRESS_GET_MODSTATUS(modId)
		if modStatus == EnumPosPressStatus.POSPRESS_RUNNING then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	PRINT("reset pos-press done")
end

function LIQ_POSPRESS_PUSH_DOWN(modId)
	PRINT("start to push down pos-press")
	local modStatus = -1
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	while 1 do
		modStatus = LIQ_POSPRESS_GET_MODSTATUS(modId)
		if modStatus == EnumPosPressStatus.POSPRESS_IDLE then
			LIQ_MOD_SET(EnumLiquidCmd.LM_INST_POSPRESS_PUSH_DOWN,modId,cmdPara)
			break
		elseif modStatus == EnumPosPressStatus.POSPRESS_ERROR then
			break
		else
			TIMER(EnumDelayValue.GETSTATUS)
		end
	end
	TIMER(EnumDelayValue.HUGE)
	while 1 do
		modStatus = LIQ_POSPRESS_GET_MODSTATUS(modId)
		if modStatus == EnumPosPressStatus.POSPRESS_RUNNING then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	PRINT("push down pos-press done")
end

function LIQ_POSPRESS_INFLATE(modId,pressValue,pressTime)
	PRINT("start to inflate pos-press")
	local modStatus = -1
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	if type(pressValue) ~= "number" then
		GOTOERROR("pressValue type is not vaild")
	end
	if type(pressTime) ~= "number" then
		GOTOERROR("pressTime type is not vaild")
	end
	if pressValue ~=0 then
		if pressValue < (0.005-(1e-6)) or pressValue > (0.5+(1e-6)) then
			GOTOERROR("pressValue value is not vaild")
		end
	end
	if pressTime ~=0 then
		if pressTime < 100 then
			GOTOERROR("pressTime value is not vaild")
		end
	end
	cmdPara.a1 = pressValue * 1000
	cmdPara.a2 = pressTime
	while 1 do
		modStatus = LIQ_POSPRESS_GET_MODSTATUS(modId)
		if modStatus == EnumPosPressStatus.POSPRESS_IDLE then
			if (pressValue > 0 and pressTime >0) then
				LIQ_MOD_SET(EnumLiquidCmd.LM_INST_POSPRESS_INFLATE,modId,cmdPara)
				break
			else
				break
			end
		elseif modStatus == EnumPosPressStatus.POSPRESS_ERROR then
			break
		else
			TIMER(EnumDelayValue.GETSTATUS)
		end
	end
	TIMER(EnumDelayValue.HUGE)
	while 1 do
		modStatus = LIQ_POSPRESS_GET_MODSTATUS(modId)
		if modStatus == EnumPosPressStatus.POSPRESS_RUNNING then
			TIMER(EnumDelayValue.GETSTATUS)
		else
			break
		end
	end
	PRINT("inflate pos-press done")
end

function LIQ_POSPRESS_PUSH_DOWN_INFLATE(modId,loopCount,pressureArray,timeArray)
	if type(loopCount) ~= "number" then
		GOTOERROR("pressCount type is not vaild")
		return
	end
	if GETTYPE(pressureArray) ~= "LMODINSD" then
		GOTOERROR("pressureArray type is not vaild")
		return
	end
	if GETTYPE(timeArray) ~= "LMODINSD" then
		GOTOERROR("timeArray type is not vaild")
		return
	end
	if loopCount>50 then
		GOTOERROR("loopCount value exceed maximunm value")
		return
	end
	if loopCount<0 then
		GOTOERROR("loopCount value must be >0 ")
		return
	end
	LIQ_POSPRESS_PUSH_DOWN(modId)
	for i = 1, loopCount, 1 do
		LIQ_POSPRESS_INFLATE(modId,pressureArray.a1,timeArray.a1)
		LIQ_POSPRESS_INFLATE(modId,pressureArray.a2,timeArray.a2)
		LIQ_POSPRESS_INFLATE(modId,pressureArray.a3,timeArray.a3)
		LIQ_POSPRESS_INFLATE(modId,pressureArray.a4,timeArray.a4)
		LIQ_POSPRESS_INFLATE(modId,pressureArray.a5,timeArray.a5)
	end
	TIMER(EnumDelayValue.USUAL)
end

--cooling command
function LIQ_COOLING_GET_MODSTATUS(modId)
	local status = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	status = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_HEATER_GET_STA,modId)
	if status~= nil then
		return status.a1
	end
end

function LIQ_COOLING_SET_TEMP_AND_START(modId,tarTemp)
	if type(tarTemp) ~= "number" then
		GOTOERROR("tarTemp type is not vaild")
		return
	end
	while 1 do
		local coolingStatus = LIQ_COOLING_GET_MODSTATUS(modId)
		if coolingStatus == EnumHeaterStatus.HEATER_ERROR then
			return
		else
			break
		end
	end
	if tarTemp>=0 and tarTemp<=105 then
		local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
		cmdPara.a1 = tarTemp
		LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_HEATER_START,modId,cmdPara)
	else
		GOTOERROR("tarTemp value is not vaild")
		return
	end
end

function LIQ_STOP_COOLING(modId)
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_HS_HEATER_STOP,modId,cmdPara)
	TIMER(EnumDelayValue.USUAL)
end

function LIQ_COOLING_WAIT_FOR_TEMP(modId,timeOut,tarTemp)
	if type(timeOut) ~= "number"then
		GOTOERROR("timeOut type is not vaild")
		return
	end
	if type(tarTemp) ~= "number"then
		GOTOERROR("tarTemp type is not vaild")
		return
	end
	if timeOut < 0 then
		GOTOERROR("timeOut value is not vaild")
		return
	end
	local getData = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	local realTemp = 0
	local isArrive = 0
	local err = 0
	local startTime = 0
	local time = 0
	startTime = _GET_TIME_MS()
	LIQ_COOLING_SET_TEMP_AND_START(modId,tarTemp)
	while 1 do
		getData = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_HS_HEATER_GET_TEMP,modId)
		if getData~=nil then
			realTemp = getData.a1
		end
		err = math.abs(realTemp - tarTemp)
		if err<0.5 then
			isArrive = 1
			break
		else
			time = _GET_TIME_MS()
			if (time - startTime)> timeOut then
				break
			else
				TIMER(EnumDelayValue.MIDDLE)
			end
		end
	end
	return isArrive
end

-- PCR command
function LIQ_PCR_GET_STA(modId)
	local status = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	status = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_PCR_GET_STA,modId)
	if status~= nil then
		return status.a1
	end
end

function LIQ_PCR_GET_SOFT_ERR(modId)
	local err = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	err = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_PCR_GET_SOFT_ERROR,modId)
	if err~= nil then
		return err.a1
	end
end

function LIQ_PCR_GET_DEV_ERR(modId)
	local err = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	err = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_PCR_GET_DEV_ERROR,modId)
	if err~= nil then
		return err.a1
	end
end

function LIQ_PCR_CTRL_COVER(modId,coverStatus)
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	if type(coverStatus) ~= "number"  then
		GOTOERROR("coverStatus type is not vaild")
		return
	end
	if coverStatus ~=1 and coverStatus ~=2 then
		GOTOERROR("coverStatus is not vaild")
		return
	end
	while 1 do
		local pcrStatus = LIQ_PCR_GET_STA(modId)
		if pcrStatus == EnumPCRStatus.PCR_BUSY then
			TIMER(EnumDelayValue.HIGH)
		else
			break
		end
	end
	cmdPara.a1 = coverStatus
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_PCR_CONTROL_COVER,modId,cmdPara)
	TIMER(EnumDelayValue.HUGE)
	while 1 do
		local pcrStatus = LIQ_PCR_GET_STA(modId)
		if pcrStatus == EnumPCRStatus.PCR_BUSY then
			TIMER(EnumDelayValue.HIGH)
		else
			break
		end
	end
end

function LIQ_PCR_CTRL_PROG_STA(modId,progStatus)
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	if type(progStatus) ~= "number"  then
		GOTOERROR("coverStatus type is not vaild")
		return
	end
	if progStatus ~=1 and progStatus ~=2 and progStatus ~= 3 then
		GOTOERROR("coverStatus is not vaild")
		return
	end
	cmdPara.a1 = progStatus
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_PCR_CONTROL_PROG_STA,modId,cmdPara)
	TIMER(EnumDelayValue.HUGE)
end

function LIQ_PCR_SELECT_PROG_EXECUTE(modId,taskSeqNo)
	local cmdPara = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	if type(taskSeqNo) ~= "number"  then
		GOTOERROR("taskSeqNo type is not vaild")
		return
	end
	if taskSeqNo <1 or taskSeqNo >20 then
		GOTOERROR("taskSeqNo is not vaild")
		return
	end
	while 1 do
		local pcrStatus = LIQ_PCR_GET_STA(modId)
		if pcrStatus == EnumPCRStatus.PCR_BUSY then
			TIMER(EnumDelayValue.HIGH)
		else
			break
		end
	end
	cmdPara.a1 = taskSeqNo
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_PCR_SELECT_PROG_EXECUTE,modId,cmdPara)
	TIMER(EnumDelayValue.HUGE)
	while 1 do
		local pcrStatus = LIQ_PCR_GET_STA(modId)
		if pcrStatus == EnumPCRStatus.PCR_BUSY then
			TIMER(EnumDelayValue.HIGH)
		else
			break
		end
	end
end

function LIQ_PCR_READ_PROG_LIST(modId)
	local taskNum = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	taskNum = LIQ_MOD_GET(EnumLiquidCmd.LM_INST_PCR_READ_PROG_LIST,modId)
	if taskNum ~= nil then
		return taskNum.a1
	end
end

--set liquid system home flag
function LIQ_SETSYSHOMEFLAG(isLDrop,isRDrop,lTipType,rTipType)
	if type(isLDrop) ~= "boolean" then
		GOTOERROR("isLDrop type is not vaild")
		return
	end
	if type(isRDrop) ~= "boolean" then
		GOTOERROR("isRDrop type is not vaild")
		return
	end

	if type(lTipType) ~= "number" then
		GOTOERROR("lTipType type is not vaild")
		return
	end
	if type(rTipType) ~= "number" then
		GOTOERROR("rTipType type is not vaild")
		return
	end
	return _LIQ_SET_SYS_HOME_FLAG(isLDrop,isRDrop,lTipType,rTipType)
end

--get liquid system home state
function LIQ_GETSYSHOMESTATE()
	return _LIQ_GET_SYS_HOME_STATE()
end

function LIQ_SYSHOME_OLD(isLDrop,isRDrop,lTipType,rTipType)
	local ret = LIQ_SETSYSHOMEFLAG(isLDrop,isRDrop,lTipType,rTipType)
	if ret == nil or ret == 0 then
		GOTOERROR("failed to set liquid sysytem home flag")
		return
	end
	local homeState = 0
	TIMER(EnumDelayValue.COMMON)
	while 1 do
		homeState = LIQ_GETSYSHOMESTATE()
		if homeState == 0 then
			TIMER(EnumDelayValue.DEFAULT)
		else
			break
		end
	end
end

function LIQ_GETTOOLINFO()
	local gripperId, piptLeftId, piptRightId
	gripperId, piptLeftId, piptRightId = _LIQ_GET_TOOL_INFO()
	return gripperId, piptLeftId, piptRightId
end

function LIQ_SYSHOME(isLDrop, isRDrop, lTipType, rTipType)
	local gripperId, piptLeftId, piptRightId
	gripperId, piptLeftId, piptRightId = LIQ_GETTOOLINFO()

	-- 1. right pipt go to zhome
	if piptRightId == EnumToolType.LIQTOOL_TYPE_PIPETTE_RIGHT then
		LIQ_PIPETZHOME(piptRightId)
	end

	-- 2. left pipt go to zhome
	if piptLeftId == EnumToolType.LIQTOOL_TYPE_PIPETTE_LEFT then
		LIQ_PIPETZHOME(piptLeftId)
	end

	-- 3. gripper to home
	LIQ_HMGRIPPER()

	-- 4. right pipt drop tip, then home right pipt
    if piptRightId == EnumToolType.LIQTOOL_TYPE_PIPETTE_RIGHT then
		if isRDrop == true then
            LIQ_DROPTIPBYTYPE(piptRightId, rTipType)
			LIQ_HMPIPET(piptRightId)
		end
	end

	-- 5. left pipt drop tip, then home left pipt
    if piptLeftId == EnumToolType.LIQTOOL_TYPE_PIPETTE_LEFT then
		if isLDrop == true then
            LIQ_DROPTIPBYTYPE(piptLeftId, lTipType)
			LIQ_HMPIPET(piptLeftId)
		end
	end

	-- 6. gantry to home
	LIQ_HMGANTRY()
end

function LIQ_SETEMPTYDET(pipetId, isEmptyDet)
	local inData = MLMODINSD(0.000,0.000,0.000,0.000,0.000)
	local curClotDetCfg = 0
	local curFoamDetCfg = 0
	local curEmptyDetCfg = 0
	curClotDetCfg, curFoamDetCfg, curEmptyDetCfg = _LIQ_GET_PIPT_DET_CFG(pipetId)
	inData.a1 = curClotDetCfg
	inData.a2 = curFoamDetCfg
	inData.a3 = isEmptyDet
	if curEmptyDetCfg == 0 then
		return
	else
		LIQ_MOD_SET(EnumLiquidCmd.LM_INST_PIPT_SET_DET,pipetId,inData)
	end
	TIMER(EnumDelayValue.USUAL)
end

function LIQ_DISABLEPIPTALARMDET(pipetId)
	local inData = MLMODINSD(0.000, 0.000, 0.000, 0.000, 0.000)
	local curClotDetCfg = 0
	local curFoamDetCfg = 0
	local curEmptyDetCfg = 0
	curClotDetCfg, curFoamDetCfg, curEmptyDetCfg = _LIQ_GET_PIPT_DET_CFG(pipetId)
	if curClotDetCfg == 0 and curFoamDetCfg == 0 and curEmptyDetCfg == 0 then
		return
	end
	inData.a1 = 0
	inData.a2 = 0
	inData.a3 = 0
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_PIPT_SET_DET, pipetId, inData)
	TIMER(EnumDelayValue.USUAL)
end

function LIQ_RESUMEPIPTALARMDET(pipetId)
	local inData = MLMODINSD(0.000, 0.000, 0.000, 0.000, 0.000)
	local clotDetCfg = 0
	local foamDetCfg = 0
	local emptyDetCfg = 0
	clotDetCfg, foamDetCfg, emptyDetCfg = _LIQ_GET_PIPT_DET_CFG(pipetId)
	if clotDetCfg == 0 and foamDetCfg == 0 and emptyDetCfg == 0 then
		return
	end
	inData.a1 = clotDetCfg
	inData.a2 = foamDetCfg
	inData.a3 = emptyDetCfg
	LIQ_MOD_SET(EnumLiquidCmd.LM_INST_PIPT_SET_DET, pipetId, inData)
	TIMER(EnumDelayValue.USUAL)
end

function LIQ_SETEXPSTEPNUM(stepNum)
	_LIQ_SET_EXP_STEP_NUM(stepNum)
end

function LIQ_SETEXPSTATUS(status)
	if status == 1 or status == 0 then
		_LIQ_SET_EXP_STATUS(status)
	else
		GOTOERROR("status value is not vaild, must be 0 or 1")
		return
	end
end

function LIQ_GETPIPTMAXVOL(piptId)
	local retValue, maxVol
	retValue, maxVol = _LIQ_GET_PIPT_MAX_VOL(piptId)
	if retValue == 0 then
		GOTOERROR("failed to get pipt max vol")
		return
	end
	return maxVol
end

function LIQ_GETPIPTINFO(piptId)
	local retValue, tipCnt, tipName, tipTypeId
	retValue, tipCnt, tipName, tipTypeId = _LIQ_GET_PIPT_INFO(piptId)
	if retValue == 0 then
		GOTOERROR("failed to get current pipt info")
		return
	end
	return tipCnt, tipName, tipTypeId
end

function LIQ_GETTIPVOL(typeName)
	local retValue, tipVol
	retValue, tipVol = _LIQ_GET_TIP_VOL(typeName)
	if retValue == 0 then
		GOTOERROR("failed to get tip vol")
		return
	end
	return tipVol
end

function LIQ_CHECKTRASHSLOT(slotLoc)
	local retValue, isTrash = _LIQ_CHECK_TRASH_SLOT(slotLoc)
	if retValue == 0 then
		GOTOERROR("error checking if slotLoc is a trash bin")
		return
	end
	return isTrash
end

function LIQ_GETTIPTYPEFROMRACK(rackTypeId)
	local retValue, tipTypeId = _LIQ_GET_TIPTYPE_FROM_RACK(rackTypeId)
	if retValue == 0 then
		GOTOERROR("error get tip type id from tip rack type id")
		return
	end
	return tipTypeId
end

function LIQ_TRANSFER_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
	local lastTipCnt, lastTipName, lastTipTypeId = LIQ_GETPIPTINFO(piptId)
	local curTipTypeId

	if lastTipCnt ~= 0 then
		if tipRackTypeId > 0 then
			curTipTypeId = LIQ_GETTIPTYPEFROMRACK(tipRackTypeId)
			if curTipTypeId ~= lastTipTypeId then
				PRINT("tip type id is not same, drop last tip")
				LIQ_DROPTIP(piptId)
				LIQ_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
			else
				if lastTipCnt ~= tipCnt then
					PRINT("tip cnt is not same, drop last tip")
					LIQ_DROPTIP(piptId)
					LIQ_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
				end
			end
		else
			local comRes = string.find(lastTipName, tipType)
			if comRes == nil then
				PRINT("tip type name is not same, drop last tip")
				LIQ_DROPTIP(piptId)
				LIQ_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
			else
				if lastTipCnt ~= tipCnt then
					PRINT("tip cnt is not same, drop last tip")
					LIQ_DROPTIP(piptId)
					LIQ_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
				end
			end
		end
	else
		LIQ_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
	end
end

function LIQ_TRANSFER_MIX_OLD(piptId, mixTimes, mixVol, mixSpeed, mixOffset, zloc, aspDelayTime, dispDelayTime, zLiqLevel, target, airVol, isAspMix)
	-- zloc: before asp zloc is aspZLoc, after disp zloc is dispZLoc
	local mixPara = MLCONPARA(mixVol, mixSpeed, zloc, 2, 0, zLiqLevel, 0, 0)
	local airHPara = MLAGAPPARA(airVol, mixSpeed, 0)
	local finalDispVol = mixVol + airVol

	-- first must aspirate head air
	if airVol > 0 then
		LIQ_AIRGAPHD(piptId, target, airHPara)
	end

	if isAspMix == 1 then		
		-- first before asp mix
		mixPara.mixType = 2
		mixPara.delayTime = aspDelayTime
		LIQ_ASPIRATE(piptId, target, mixPara)
		mixPara.zLoc = mixPara.zLoc + mixOffset
		mixPara.mixType = 3
		if mixTimes == 1 then
			mixPara.volume = finalDispVol
		else
			mixPara.volume = mixVol
		end
		mixPara.delayTime = dispDelayTime
		LIQ_DISPENSE(piptId, target, mixPara)
	else
		-- first after disp mix
		mixPara.mixType = 3
		mixPara.zLoc = mixPara.zLoc - mixOffset
		mixPara.delayTime = aspDelayTime
		LIQ_ASPIRATE(piptId, target, mixPara)
		mixPara.zLoc = mixPara.zLoc + mixOffset
		if mixTimes == 1 then
			mixPara.volume = finalDispVol
		else
			mixPara.volume = mixVol
		end
		mixPara.delayTime = dispDelayTime
		LIQ_DISPENSE(piptId, target, mixPara)
	end

	if mixTimes >= 2 then
		-- second to mixTimes mix
		for i = 2, mixTimes do
			mixPara.mixType = 3
			mixPara.zLoc = mixPara.zLoc - mixOffset
			mixPara.delayTime = aspDelayTime
			LIQ_ASPIRATE(piptId, target, mixPara)
			mixPara.zLoc = mixPara.zLoc + mixOffset
			if i == mixTimes then
				mixPara.volume = finalDispVol
			else
				mixPara.volume = mixVol
			end
			mixPara.delayTime = dispDelayTime
			LIQ_DISPENSE(piptId, target, mixPara)
		end
	end
end

-- transfer for once aspirate and dispense whit N to N model
-- local aspTchPara = MLTCHPARA(aspTchSpeed, aspTchZLoc, aspTchInHoleLoc, aspTchOpTime)
-- local dispTchPara = MLTCHPARA(dispTchSpeed, dispTchZLoc, dispTchInHoleLoc, dispTchOpTime)
-- local aspColDatas = {{1, 1}, {2, 2}, xx}
-- local dispColDatas = {{1, 1}, {2, 2}, xx}
-- aspColDatas.size must be equal to dispColDatas.size
function LIQ_TRANSFER_ONCE_OLD(
	isDropTip, isReuTip,
    piptId, tipType, tipCnt,
	headVol, tailVol, targetVol,
    aspSlotLoc, dispSlotLoc,
    aspParaSpeed, aspParaZLoc, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow,
    dispParaSpeed, dispParaZLoc, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow,
	aspMix, aspMixTimes, aspMixVol, aspMixSpeed,
	dispMix,dispMixTimes, dispMixVol, dispMixSpeed,
	mixOffset,
	aspTouch, aspTchPara,
	dispTouch, dispTchPara,
	aspColDatas,
	dispColDatas)

	local tipMaxVol = LIQ_GETTIPVOL(tipType)
	local piptMaxVol = LIQ_GETPIPTMAXVOL(piptId)

	local curTipVol = targetVol + tailVol  -- Head air vol are not counted in the total volume
	local curPiptVol = headVol + targetVol + tailVol
	if curTipVol > tipMaxVol  or curPiptVol > piptMaxVol then
		GOTOERROR("total aspirate volume exceeds the range")
		return
	end

	if #aspColDatas ~= #dispColDatas then
		GOTOERROR("aspirate / dispense column coding values are not vaild")
		return
	end

	-- if enable before aspiration mix, disable liq level detection and follow
	if aspMix == 1 then
		aspParaLevelDet = 0
		aspParaLevelFollow = 0
	end

	local dispVol = headVol + tailVol + targetVol

    local aspTarget = MLTARGET(aspSlotLoc, 1, 1)
    local dispTarget = MLTARGET(dispSlotLoc, 1, 1)

    local aspPara = MLCONPARA(targetVol, aspParaSpeed, aspParaZLoc, 0, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow)       
    local dispPara = MLCONPARA(dispVol, dispParaSpeed, dispParaZLoc, 0, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow)

	local airHPara = MLAGAPPARA(headVol, aspParaSpeed, 0)
	local airTPara = MLAGAPPARA(tailVol, aspParaSpeed, 0)

	LIQ_TRANSFER_PICKUPTIP(piptId, tipType, tipCnt)

	for i = 1, #aspColDatas do
		aspTarget.colNo = aspColDatas[i][1]
		aspTarget.rowNo = aspColDatas[i][2]
		dispTarget.colNo = dispColDatas[i][1]
		dispTarget.rowNo = dispColDatas[i][2]

		if isReuTip == 0 and i > 1 then
			LIQ_PICKUPTIP(piptId, tipType, tipCnt)
		end

		if aspMix == 1 then
			LIQ_TRANSFER_MIX_OLD(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, aspTarget, headVol, 1)
		end

		if headVol > 0 then
			LIQ_AIRGAPHD(piptId, aspTarget, airHPara)
		end

		LIQ_ASPIRATE(piptId, aspTarget, aspPara)

		if aspTouch == 1 then
			LIQ_TOUCHTIP(piptId, aspTarget, aspTchPara)
		end

		if tailVol > 0 then
    		LIQ_AIRGAPTL(piptId, airTPara)
		end

		LIQ_DISPENSE(piptId, dispTarget, dispPara)

		if dispMix == 1 then
			LIQ_TRANSFER_MIX_OLD(piptId, dispMixTimes, dispMixVol, dispMixSpeed, mixOffset, dispParaZLoc, aspParaDelayTime, dispParaDelayTime, dispParaZLiqLevel, dispTarget, headVol, 0)
		end

		if dispTouch == 1 then
			LIQ_TOUCHTIP(piptId, dispTarget, dispTchPara)
		end

		if isReuTip == 0 then
			LIQ_DROPTIP(piptId)
		end
	end

	if isReuTip == 1 and isDropTip == 1 then
		LIQ_DROPTIP(piptId)
	end

	LIQ_HMPIPET(piptId)
end

-- transfer for one aspirate and multi dispense from thor sepcification data
-- local aspTchPara = MLTCHPARA(aspTchSpeed, aspTchZLoc, aspTchInHoleLoc, aspTchOpTime)
-- local dispColDatas = {{1, 1}, {1, 4}, {1, 5}}
function LIQ_TRANSFER_MULT_SPEC_OLD(
    isDropTip, setInfiDisp,
    piptId, tipType, tipCnt,
    headVol, tailVol, otherVol, infiVol, mDispVol,
    aspSlotLoc, aspColNo, aspRowNo, 
    dispSlotLoc, 
    airHParaSpeed, 
	airTParaSpeed,
    aspParaSpeed, aspParaZLoc, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow,
    dispParaSpeed, dispParaZLoc, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow,
	aspMix, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset,
	aspTouch, aspTchPara,
	dispTouch, dispTchPara,
	dispColDatas)

	local tipMaxVol = LIQ_GETTIPVOL(tipType)
	local piptMaxVol = LIQ_GETPIPTMAXVOL(piptId)

	local maxVol
	if tipMaxVol + headVol <= piptMaxVol then
		maxVol = tipMaxVol + headVol
	elseif tipMaxVol < piptMaxVol and tipMaxVol + headVol > piptMaxVol then
		maxVol = tipMaxVol
	elseif tipMaxVol >= piptMaxVol then
		maxVol = piptMaxVol
	end

	-- if enable before aspiration mix, disable liq level detection and follow
	if aspMix == 1 then
		aspParaLevelDet = 0
		aspParaLevelFollow = 0
	end

	local LLiqTargetAspAirHead = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                                       
	local LLiqTargetAsp = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                            
	local LLiqTargetDisp = MLTARGET(dispSlotLoc, 1, 1)                            
	local LLiqTargetDispOthVol = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                     
	local LLiqTargetDispInfi = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                       

	local LLiqAirGParaH = MLAGAPPARA(headVol, airHParaSpeed, 0)                      
	local LLiqAirGParaT = MLAGAPPARA(tailVol, airTParaSpeed, 0)                        
	local LLiqAspPara = MLCONPARA(10, aspParaSpeed, aspParaZLoc, 0, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow)               
	local LLiqDispPara = MLCONPARA(10, dispParaSpeed, dispParaZLoc, 0, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow)              
	local LLiqDispParaOther = MLCONPARA(10, dispParaSpeed, dispParaZLoc, 0, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow)         
	local LLiqDispParaInfi= MLCONPARA(10, dispParaSpeed, dispParaZLoc, 0, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow)           
	
	local nNumDispFull_1 = IDIV(maxVol - headVol - tailVol - infiVol, mDispVol)
	local nNumDispFull_2 = IDIV(maxVol - headVol - otherVol - infiVol, mDispVol)
	local nNumDispFull = math.min(nNumDispFull_1, nNumDispFull_2)

	local dispCnt = #dispColDatas

	if dispCnt > nNumDispFull then
		local nNumAsp1 = IDIV(dispCnt, nNumDispFull)
		local nNumdisp2 = dispCnt - nNumAsp1 * nNumDispFull    

		LIQ_TRANSFER_PICKUPTIP(piptId, tipType, tipCnt)

		local disIdx = 1
		for k = 1, nNumAsp1 do
			if k > 1 and setInfiDisp == 0 then               
				LIQ_PICKUPTIP(piptId, tipType, tipCnt)
			end

			if aspMix == 1 then
				LIQ_TRANSFER_MIX_OLD(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, LLiqTargetAsp, headVol, 1)		
			end
			if headVol > 0 then
				LLiqAirGParaH.volume = headVol
				LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH)
			end
			LLiqAspPara.volume = otherVol + nNumDispFull * mDispVol + infiVol
			LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara)
			if otherVol > 0 then
				LLiqDispParaOther.volume = otherVol
				LLiqDispParaOther.mixType = 3
				LIQ_DISPENSE(piptId, LLiqTargetDispOthVol, LLiqDispParaOther)
				LLiqDispParaOther.mixType = 0
			end

			if aspTouch == 1 then
				LIQ_TOUCHTIP(piptId, LLiqTargetAsp, aspTchPara)
			end
			
			if tailVol > 0 then
				LLiqAirGParaT.volume = tailVol
				LIQ_AIRGAPTL(piptId, LLiqAirGParaT)
			end

			for j = 1 , nNumDispFull do
				if j == 1 then
					LLiqDispPara.volume = mDispVol + tailVol
				else
					LLiqDispPara.volume = mDispVol
				end
				LLiqTargetDisp.colNo = dispColDatas[disIdx][1]
				LLiqTargetDisp.rowNo = dispColDatas[disIdx][2]
				LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara)
				disIdx = disIdx + 1

				if dispTouch == 1 then
					LIQ_TOUCHTIP(piptId, LLiqTargetDisp, dispTchPara)
				end
			end

			if setInfiDisp == 1 then
				if infiVol > 0 then
					LLiqDispParaInfi.volume = headVol + infiVol
					LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi)
				end
			else
				LIQ_DROPTIP(piptId)
			end
		end
		
		if nNumdisp2 > 0 then
			if setInfiDisp == 0 then
				LIQ_PICKUPTIP(piptId, tipType, tipCnt)
			end

			if aspMix == 1 then
				LIQ_TRANSFER_MIX_OLD(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, LLiqTargetAsp, headVol, 1)				
			end
			
			if headVol > 0 then
				LLiqAirGParaH.volume = headVol
				LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH)
			end
			LLiqAspPara.volume = otherVol + nNumdisp2 * mDispVol + infiVol
			LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara)
			if otherVol > 0 then
				LLiqDispParaOther.volume = otherVol
				LLiqDispParaOther.mixType = 3
				LIQ_DISPENSE(piptId, LLiqTargetDispOthVol, LLiqDispParaOther)
				LLiqDispParaOther.mixType = 0
			end

			if aspTouch == 1 then
				LIQ_TOUCHTIP(piptId, LLiqTargetAsp, aspTchPara)
			end

			if tailVol > 0 then
				LLiqAirGParaT.volume = tailVol
				LIQ_AIRGAPTL(piptId, LLiqAirGParaT)
			end

			for n = 1 , nNumdisp2  do
				if n == 1 then
					LLiqDispPara.volume = mDispVol + tailVol
				else
					LLiqDispPara.volume = mDispVol
				end
				LLiqTargetDisp.colNo = dispColDatas[disIdx][1]
				LLiqTargetDisp.rowNo = dispColDatas[disIdx][2]
				LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara)
				disIdx = disIdx + 1

				if dispTouch == 1 then
					LIQ_TOUCHTIP(piptId, LLiqTargetDisp, dispTchPara)
				end

			end

			if setInfiDisp == 1 then
				if infiVol > 0 then
					LLiqDispParaInfi.volume = headVol + infiVol
					LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi)
				end
			else
				LIQ_DROPTIP(piptId)
			end
		end
	else
		LIQ_TRANSFER_PICKUPTIP(piptId, tipType, tipCnt)

		if aspMix == 1 then
			LIQ_TRANSFER_MIX_OLD(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, LLiqTargetAsp, headVol, 1)				
		end

		if headVol > 0 then
			LLiqAirGParaH.volume = headVol
			LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH)
		end
		LLiqAspPara.volume = otherVol + mDispVol * dispCnt +  infiVol
		LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara)
		if otherVol > 0 then
			LLiqDispParaOther.volume = otherVol
			LLiqDispParaOther.mixType = 3
			LIQ_DISPENSE(piptId, LLiqTargetDispOthVol, LLiqDispParaOther)
			LLiqDispParaOther.mixType = 0
		end

		if aspTouch == 1 then
			LIQ_TOUCHTIP(piptId, LLiqTargetAsp, aspTchPara)
		end
		
		if tailVol > 0 then
			LLiqAirGParaT.volume = tailVol
			LIQ_AIRGAPTL(piptId, LLiqAirGParaT)
		end

		for k = 1, dispCnt do
			if k == 1 then
				LLiqDispPara.volume = mDispVol + tailVol
			else
				LLiqDispPara.volume = mDispVol
			end
			LLiqTargetDisp.colNo = dispColDatas[k][1]
			LLiqTargetDisp.rowNo = dispColDatas[k][2]
			LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara)

			if dispTouch == 1 then
				LIQ_TOUCHTIP(piptId, LLiqTargetDisp, dispTchPara)
			end
		end

		if setInfiDisp == 1 then
			if infiVol > 0 then
				LLiqDispParaInfi.volume = headVol + infiVol
				LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi)
			end
		else
			LIQ_DROPTIP(piptId)
		end
	end
	
	if setInfiDisp == 1 and isDropTip == 1 then
		LIQ_DROPTIP(piptId)
	end

	LIQ_HMPIPET(piptId)
end

function LIQ_TRANSFER_MIX(piptId, mixTimes, mixVol, mixSpeed, mixOffset, zloc, aspDelayTime, dispDelayTime, zLiqLevel, target, airVol, isAspMix, isSameSLot, lastPickTip, isLastInfiDisped, blowSlotType)
	-- zloc: before asp zloc is aspZLoc, after disp zloc is dispZLoc
	local mixPara = MLCONPARA(mixVol, mixSpeed, zloc, 2, 0, zLiqLevel, 0, 0)
	local airHPara = MLAGAPPARA(airVol, mixSpeed, 0)
	local finalDispVol = mixVol + airVol
	local zPosType = 1	-- 1:zhome 2:labware top
	-- first must aspirate head air

	if isAspMix == 1 then
		if lastPickTip == 1 then
			zPosType = 1
		else
			if isSameSLot == 1 and blowSlotType ~= 3 then
				zPosType = 2
			else
				if isLastInfiDisped == 1 or blowSlotType == 1 then
					zPosType = 2
				else
					zPosType = 1
				end
			end
		end
	else
		zPosType = 2
	end

	if airVol > 0 then
		LIQ_AIRGAPHD(piptId, target, airHPara, zPosType)
	end

	if isAspMix == 1 then
		-- first before asp mix
		mixPara.mixType = 2
		mixPara.delayTime = aspDelayTime
		if zPosType == 1 then
			LIQ_ASPIRATE(piptId, target, mixPara, 1)
		else
			LIQ_ASPIRATE(piptId, target, mixPara, 2)
		end
		mixPara.zLoc = mixPara.zLoc + mixOffset
		mixPara.mixType = 3
		if mixTimes == 1 then
			mixPara.volume = finalDispVol
		else
			mixPara.volume = mixVol
		end
		mixPara.delayTime = dispDelayTime
		LIQ_DISPENSE(piptId, target, mixPara, 2)
	else
		-- first after disp mix
		mixPara.mixType = 3
		mixPara.zLoc = mixPara.zLoc - mixOffset
		mixPara.delayTime = aspDelayTime
		LIQ_ASPIRATE(piptId, target, mixPara, 2)
		mixPara.zLoc = mixPara.zLoc + mixOffset
		if mixTimes == 1 then
			mixPara.volume = finalDispVol
		else
			mixPara.volume = mixVol
		end
		mixPara.delayTime = dispDelayTime
		LIQ_DISPENSE(piptId, target, mixPara, 2)
	end

	if mixTimes >= 2 then
		-- second to mixTimes mix
		for i = 2, mixTimes do
			mixPara.mixType = 3
			mixPara.zLoc = mixPara.zLoc - mixOffset
			mixPara.delayTime = aspDelayTime
			LIQ_ASPIRATE(piptId, target, mixPara, 2)
			mixPara.zLoc = mixPara.zLoc + mixOffset
			if i == mixTimes then
				mixPara.volume = finalDispVol
			else
				mixPara.volume = mixVol
			end
			mixPara.delayTime = dispDelayTime
			LIQ_DISPENSE(piptId, target, mixPara, 2)
		end
	end
end

-- transfer for once aspirate and dispense whit N to N model
-- local aspTchPara = MLTCHPARA(aspTchSpeed, aspTchZLoc, aspTchInHoleLoc, aspTchOpTime)
-- local dispTchPara = MLTCHPARA(dispTchSpeed, dispTchZLoc, dispTchInHoleLoc, dispTchOpTime)
-- local aspColDatas = {{1, 1}, {2, 2}, xx}
-- local dispColDatas = {{1, 1}, {2, 2}, xx}
-- aspColDatas.size must be equal to dispColDatas.size
function LIQ_TRANSFER_ONCE(
	isDropTip, isReuTip,
	isPickReuTip, pickCol, pickRow,
	isBlowOut, blowSlotType, blowIn, blowZLoc, blowSpeed, trashSlotLoc,
    piptId, tipType, tipCnt,
	headVol, tailVol, targetVol,
    aspSlotLoc, dispSlotLoc,
    aspParaSpeed, aspParaZLoc, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow,
    dispParaSpeed, dispParaZLoc, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow,
	aspMix, aspMixTimes, aspMixVol, aspMixSpeed,
	dispMix,dispMixTimes, dispMixVol, dispMixSpeed,
	mixOffset,
	aspTouch, aspTchPara,
	dispTouch, dispTchPara,
	aspColDatas,
	dispColDatas, ...)

	local args = {...}
    local antiDrip = 0
	local tipRackTypeId = -1
	local reuRackSlotLoc = 0

    if #args >= 1 then
		if type(args[1]) == "number" then	-- 1. antiDrip parameter
        	antiDrip = args[1]
		end
		if type(args[2]) == "number" then	-- 2. tipRackTypeId parameter
        	tipRackTypeId = args[2]
		end
		if type(args[3]) == "number" then	-- 3. reusable tip rack slotLoc parameter
			reuRackSlotLoc = args[3]
		end
    end

	if #aspColDatas ~= #dispColDatas then
		GOTOERROR("aspirate / dispense column coding values are not vaild")
		return
	end

	local isDispTrash = LIQ_CHECKTRASHSLOT(dispSlotLoc)

	-- if enable before aspiration mix, disable liq level detection and follow
	if aspMix == 1 then
		aspParaLevelDet = 0
		aspParaLevelFollow = 0
	end

	local dispVol = headVol + tailVol + targetVol
	local headAirVol = headVol + blowIn

    local aspTarget = MLTARGET(aspSlotLoc, 1, 1)
    local dispTarget = MLTARGET(dispSlotLoc, 1, 1)

    local aspPara = MLCONPARA(targetVol, aspParaSpeed, aspParaZLoc, 0, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow)       
    local dispPara = MLCONPARA(dispVol, dispParaSpeed, dispParaZLoc, 0, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow)

	local airHPara = MLAGAPPARA(headAirVol, aspParaSpeed, 0)
	local airTPara = MLAGAPPARA(tailVol, aspParaSpeed, 0)

	local blowSlotLoc = 0
	if isBlowOut == 1 then
		if blowSlotType == 1 then
			blowSlotLoc = aspSlotLoc
		elseif blowSlotType == 2 then
			blowSlotLoc = dispSlotLoc
		else
			blowSlotLoc = trashSlotLoc
		end
	end
	local blowTarget = MLTARGET(blowSlotLoc, 1, 1)

	local isSameSlot = 0
	if aspSlotLoc == dispSlotLoc then
		isSameSlot = 1
	end

	if isPickReuTip == 1 then
		local lastTipCnt, _, __ = LIQ_GETPIPTINFO(piptId)
		if lastTipCnt ~= 0 then
			LIQ_DROPTIP(piptId)
		end
		LIQ_PICKUPREUTIP(piptId, tipType, pickCol, pickRow, tipCnt, reuRackSlotLoc)
	else
		LIQ_TRANSFER_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
	end

	for i = 1, #aspColDatas do
		aspTarget.colNo = aspColDatas[i][1]
		aspTarget.rowNo = aspColDatas[i][2]
		dispTarget.colNo = dispColDatas[i][1]
		dispTarget.rowNo = dispColDatas[i][2]

		if (isReuTip == 0 and i > 1 and isPickReuTip == 0) then
			LIQ_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
		end

		local lastPickTip = 0
		if i == 1 or (isReuTip == 0 and i > 1 and isPickReuTip == 0) then
			lastPickTip = 1
		end

		if aspMix == 1 then
			LIQ_TRANSFER_MIX(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, aspTarget, headVol, 1, isSameSlot, lastPickTip, 0, blowSlotType)
		end

		local lastAirHome = 1	-- 1:zhome 2:labware top
		if lastPickTip == 1 then
			if aspMix == 1 then
				lastAirHome = 2
			else
				lastAirHome = 1
			end
		else
			if isSameSlot == 1 and blowSlotType ~= 3 then
				lastAirHome = 2
			else
				if aspMix == 1 or blowSlotType == 1 then
					lastAirHome = 2
				else
					lastAirHome = 1
				end
			end
		end

		if headAirVol > 0 then
			LIQ_AIRGAPHD(piptId, aspTarget, airHPara, lastAirHome)
		end

		-- calc aspirate path for touch
		if aspTouch == 1 then
			aspPara.mixType = 2
		end

		if tailVol > 0 then
			LIQ_ASPIRATE(piptId, aspTarget, aspPara, lastAirHome, 0)
		else
			LIQ_ASPIRATE(piptId, aspTarget, aspPara, lastAirHome, antiDrip)
		end

		if aspTouch == 1 then
			LIQ_TOUCHTIP(piptId, aspTarget, aspTchPara)
		end

		if tailVol > 0 then
			if isSameSlot == 1 then
				LIQ_AIRGAPTL(piptId, aspTarget, airTPara, 2, antiDrip)
			else
				LIQ_AIRGAPTL(piptId, aspTarget, airTPara, 1, antiDrip)
			end
		end

		if dispTouch == 1 and dispMix ~= 1 and isBlowOut ~= 1 then
			dispPara.mixType = 2
		end

		if isSameSlot == 1 then
			LIQ_DISPENSE(piptId, dispTarget, dispPara, 2, 0)
		else
			LIQ_DISPENSE(piptId, dispTarget, dispPara, 1, 0)
		end

		if dispMix == 1 then
			LIQ_TRANSFER_MIX(piptId, dispMixTimes, dispMixVol, dispMixSpeed, mixOffset, dispParaZLoc, aspParaDelayTime, dispParaDelayTime, dispParaZLiqLevel, dispTarget, headVol, 0, 0, 0, 0, blowSlotType)
		end

		if isBlowOut == 1 then
			local toZPosType = 1
			local pathType = 0	-- 1 spec 0 others
			if blowSlotType == 1 then
				blowTarget.colNo = aspColDatas[i][1]
				blowTarget.rowNo = aspColDatas[i][2]
				if isSameSlot == 1 then
					toZPosType = 2
				else
					toZPosType = 1
				end
			elseif blowSlotType == 2 and isDispTrash == 0 then
				blowTarget.colNo = dispColDatas[i][1]
				blowTarget.rowNo = dispColDatas[i][2]
				pathType = 1
			elseif blowSlotType == 2 and isDispTrash == 1 then
				toZPosType = 3
			elseif blowSlotType == 3 and isDispTrash == 1 then
				toZPosType = 3
			else
				toZPosType = 1
			end

			LIQ_BLOWOUT(piptId, blowTarget, blowIn, blowZLoc, blowSpeed, toZPosType, pathType)
		end

		if dispTouch == 1 then
			local tchTarget = dispTarget
			local tchPara = dispTchPara
			if isBlowOut == 1 and blowSlotType == 1 then
				if aspTouch == 1 then
					tchTarget = aspTarget
					tchPara = aspTchPara
					LIQ_TOUCHTIP(piptId, tchTarget, tchPara)
				end
			else
				LIQ_TOUCHTIP(piptId, tchTarget, tchPara)
			end
		end

		if isReuTip == 0 and isPickReuTip == 0 then
			if isBlowOut == 1 then
				if blowSlotType == 3 or (blowSlotType == 2 and isDispTrash == 1) then
					LIQ_DROPTIP(piptId, 3)
				else
					LIQ_DROPTIP(piptId)
				end
			else
				if isDispTrash == 1 then
					LIQ_DROPTIP(piptId, 3)
				else
					LIQ_DROPTIP(piptId)
				end
			end
		end
	end

	if isReuTip == 1 and isDropTip == 1 and isPickReuTip == 0 then
		if isBlowOut == 1 then
			if blowSlotType == 3 or (blowSlotType == 2 and isDispTrash == 1) then
				LIQ_DROPTIP(piptId, 3)
			else
				LIQ_DROPTIP(piptId)
			end
		else
			if isDispTrash == 1 then
				LIQ_DROPTIP(piptId, 3)
			else
				LIQ_DROPTIP(piptId)
			end
		end
	end

	if isPickReuTip == 1 then
		LIQ_RETTIP(piptId)
	end

	LIQ_HMPIPET(piptId)
end

-- transfer for one aspirate and multi dispense from thor sepcification data
-- local aspTchPara = MLTCHPARA(aspTchSpeed, aspTchZLoc, aspTchInHoleLoc, aspTchOpTime)
-- local dispColDatas = {{1, 1}, {1, 4}, {1, 5}}
function LIQ_TRANSFER_MULT_SPEC(
    isDropTip, setInfiDisp,
	isPickReuTip, pickCol, pickRow,
    piptId, tipType, tipCnt,
    headVol, tailVol, otherVol, infiVol, mDispVol,
    aspSlotLoc, aspColNo, aspRowNo,
    dispSlotLoc,
    airHParaSpeed,
	airTParaSpeed,
    aspParaSpeed, aspParaZLoc, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow,
    dispParaSpeed, dispParaZLoc, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow,
	aspMix, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset,
	aspTouch, aspTchPara,
	dispTouch, dispTchPara,
	dispColDatas, ...)

	local args = {...}
    local antiDrip = 0
	local tipRackTypeId = -1
	local reuRackSlotLoc = 0

    if #args >= 1 then
		if type(args[1]) == "number" then	-- 1. antiDrip parameter
        	antiDrip = args[1]
		end
		if type(args[2]) == "number" then	-- 2. tipRackTypeId parameter
        	tipRackTypeId = args[2]
		end
		if type(args[3]) == "number" then	-- 3. reusable tip rack slotLoc parameter
			reuRackSlotLoc = args[3]
		end
    end

	local currentVol = 0

	local tipMaxVol = LIQ_GETTIPVOL(tipType)
	local piptMaxVol = LIQ_GETPIPTMAXVOL(piptId)

	local maxVol
	if tipMaxVol + headVol <= piptMaxVol then
		maxVol = tipMaxVol + headVol
	elseif tipMaxVol < piptMaxVol and tipMaxVol + headVol > piptMaxVol then
		maxVol = tipMaxVol
	elseif tipMaxVol >= piptMaxVol then
		maxVol = piptMaxVol
	end

	-- if enable before aspiration mix, disable liq level detection and follow
	if aspMix == 1 then
		aspParaLevelDet = 0
		aspParaLevelFollow = 0
	end

	local LLiqTargetAspAirHead = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)
	local LLiqTargetAspAirTail = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                                     
	local LLiqTargetAsp = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                           
	local LLiqTargetDisp = MLTARGET(dispSlotLoc, 1, 1)                            
	local LLiqTargetDispOthVol = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                     
	local LLiqTargetDispInfi = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                       

	local LLiqAirGParaH = MLAGAPPARA(headVol, airHParaSpeed, 0)                      
	local LLiqAirGParaT = MLAGAPPARA(tailVol, airTParaSpeed, 0)                        
	local LLiqAspPara = MLCONPARA(10, aspParaSpeed, aspParaZLoc, 0, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow)               
	local LLiqDispPara = MLCONPARA(10, dispParaSpeed, dispParaZLoc, 0, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow)              
	local LLiqDispParaOther = MLCONPARA(10, dispParaSpeed, aspParaZLoc, 3, dispParaDelayTime, aspParaZLiqLevel, 0, 0)
	local LLiqDispParaInfi= MLCONPARA(10, dispParaSpeed, aspParaZLoc, 0, dispParaDelayTime, aspParaZLiqLevel, 0, 0)   

	local nNumDispFull_1 = IDIV(maxVol - headVol - tailVol - infiVol, mDispVol)
	local nNumDispFull_2 = IDIV(maxVol - headVol - otherVol - infiVol, mDispVol)
	local nNumDispFull = math.min(nNumDispFull_1, nNumDispFull_2)

	local dispCnt = #dispColDatas

	local isSameSlot = 0
	if aspSlotLoc == dispSlotLoc then
		isSameSlot = 1
	end

	if dispCnt > nNumDispFull then
		local nNumAsp1 = IDIV(dispCnt, nNumDispFull)
		local nNumdisp2 = dispCnt - nNumAsp1 * nNumDispFull  

		if isPickReuTip == 1 then
			local lastTipCnt, _, __ = LIQ_GETPIPTINFO(piptId)
			if lastTipCnt ~= 0 then
				LIQ_DROPTIP(piptId)
			end
			LIQ_PICKUPREUTIP(piptId, tipType, pickCol, pickRow, tipCnt, reuRackSlotLoc)
		else
			LIQ_TRANSFER_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
		end

		local isLastInfiDisped = 0

		local disIdx = 1
		for k = 1, nNumAsp1 do
			if k > 1 and setInfiDisp == 0 and isPickReuTip == 0 then
				LIQ_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
			end

			local lastPickTip = 0
			if k == 1 or (k > 1  and setInfiDisp == 0 and isPickReuTip == 0) then
				lastPickTip = 1
			end

			if aspMix == 1 then
				LIQ_TRANSFER_MIX(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, LLiqTargetAsp, headVol, 1, isSameSlot, lastPickTip, isLastInfiDisped, 0)	
			end

			local lastAirHome = 1 -- 1:zhome 2:labware top
			if k == 1 then
				if aspMix == 1 then
					lastAirHome = 2
				else
					lastAirHome = 1
				end
			else
				if isSameSlot == 1 then
					lastAirHome = 2
				else
					if aspMix == 1 then
						lastAirHome = 2
					else
						if isLastInfiDisped == 1 then
							lastAirHome = 2
						else
							lastAirHome = 1
						end
					end
				end
			end

			if headVol > 0 then
				LLiqAirGParaH.volume = headVol
				LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH, lastAirHome)
			end

			LLiqAspPara.volume = otherVol + nNumDispFull * mDispVol + infiVol
			if otherVol > 0 then
				LLiqAspPara.mixType = 2
				LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara, lastAirHome, 0)
				LLiqAspPara.mixType = 0
			else
				if aspTouch == 1 then
					LLiqAspPara.mixType = 2
				end

				if tailVol > 0 then
					LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara, lastAirHome, 0)
				else
					LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara, lastAirHome, antiDrip)
				end
			end

			currentVol = currentVol + LLiqAspPara.volume

			if otherVol > 0 then
				LLiqDispParaOther.volume = otherVol
				LIQ_DISPENSE(piptId, LLiqTargetDispOthVol, LLiqDispParaOther, 2)
				currentVol = currentVol - otherVol
			end

			if aspTouch == 1 then
				LIQ_TOUCHTIP(piptId, LLiqTargetAsp, aspTchPara)
			end

			if tailVol > 0 then
				LLiqAirGParaT.volume = tailVol
				if isSameSlot == 1 then
					LIQ_AIRGAPTL(piptId, LLiqTargetAspAirTail, LLiqAirGParaT, 2, antiDrip)
				else
					LIQ_AIRGAPTL(piptId, LLiqTargetAspAirTail, LLiqAirGParaT, 1, antiDrip)
				end
				currentVol = currentVol + tailVol
			end

			for j = 1 , nNumDispFull do
				if nNumDispFull == 1 then
					if setInfiDisp == 1 then
						LLiqDispPara.volume = mDispVol + tailVol
					else
						LLiqDispPara.volume = mDispVol + tailVol + headVol
					end
				else
					if j == 1 then
						LLiqDispPara.volume = mDispVol + tailVol
						elseif j == nNumDispFull then
							if setInfiDisp == 1 then
								LLiqDispPara.volume = mDispVol
							else
								LLiqDispPara.volume = mDispVol + headVol
							end
					else
						LLiqDispPara.volume = mDispVol
					end
				end

				if dispTouch == 1 then
					LLiqDispPara.mixType = 2
				end

				LLiqTargetDisp.colNo = dispColDatas[disIdx][1]
				LLiqTargetDisp.rowNo = dispColDatas[disIdx][2]

				if j == 1 and isSameSlot == 0 then
					if currentVol > 0  and (currentVol - LLiqDispPara.volume > 0) then
						LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 1, antiDrip)
					else
						LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 1, 0)
					end
				else
					if currentVol > 0  and (currentVol - LLiqDispPara.volume > 0) then
						LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 2, antiDrip)
					else
						LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 2, 0)
					end
				end

				disIdx = disIdx + 1
				currentVol = currentVol - LLiqDispPara.volume

				if dispTouch == 1 then
					LIQ_TOUCHTIP(piptId, LLiqTargetDisp, dispTchPara)
				end
			end

			isLastInfiDisped = 0
			if setInfiDisp == 1 then
				if infiVol > 0 then
					LLiqDispParaInfi.volume = headVol + infiVol
					isLastInfiDisped = 1
					if isSameSlot == 1 then
						LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi, 2)
					else
						LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi, 1)
					end

					currentVol = currentVol - LLiqDispParaInfi.volume
				end
			else
				if isPickReuTip == 0 then
					LIQ_DROPTIP(piptId)
				end
			end
		end

		if nNumdisp2 > 0 then
			currentVol = 0
			local lastPickTip = 0
			if setInfiDisp == 0 and isPickReuTip == 0 then
				LIQ_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
				lastPickTip = 1
			end

			if aspMix == 1 then
				LIQ_TRANSFER_MIX(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, LLiqTargetAsp, headVol, 1, isSameSlot, lastPickTip, isLastInfiDisped, 0)
			end

			local lastAirHome = 1	-- 1:zhome 2:labware top
			if lastPickTip == 1 and aspMix == 0 then
				lastAirHome = 1
			else
				if isSameSlot == 1 then
					lastAirHome = 2
				else
					if aspMix == 1 then
						lastAirHome = 2
					else
						if isLastInfiDisped == 1 then
							lastAirHome = 2
						else
							lastAirHome = 1
						end
					end
				end
			end

			if headVol > 0 then
				LLiqAirGParaH.volume = headVol
				LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH, lastAirHome)
			end

			LLiqAspPara.volume = otherVol + nNumdisp2 * mDispVol + infiVol
			if otherVol > 0 then
				LLiqAspPara.mixType = 2
				LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara, lastAirHome)
				LLiqAspPara.mixType = 0
			else
				if aspTouch == 1 then
					LLiqAspPara.mixType = 2
				end
				LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara, lastAirHome)
			end

			currentVol = currentVol + LLiqAspPara.volume

			if otherVol > 0 then
				LLiqDispParaOther.volume = otherVol
				LIQ_DISPENSE(piptId, LLiqTargetDispOthVol, LLiqDispParaOther, 2)
				currentVol = currentVol - otherVol
			end

			if aspTouch == 1 then
				LIQ_TOUCHTIP(piptId, LLiqTargetAsp, aspTchPara)
			end

			if tailVol > 0 then
				LLiqAirGParaT.volume = tailVol
				if isSameSlot == 1 then
					LIQ_AIRGAPTL(piptId, LLiqTargetAspAirTail, LLiqAirGParaT, 2, antiDrip)
				else
					LIQ_AIRGAPTL(piptId, LLiqTargetAspAirTail, LLiqAirGParaT, 1, antiDrip)
				end
				currentVol = currentVol + tailVol
			end

			for n = 1 , nNumdisp2  do
				if nNumdisp2 == 1 then
					if setInfiDisp == 1 then
						LLiqDispPara.volume = mDispVol + tailVol
					else
						LLiqDispPara.volume = mDispVol + tailVol + headVol
					end
				else
					if n == 1 then
						LLiqDispPara.volume = mDispVol + tailVol
						elseif n == nNumdisp2 then
							if setInfiDisp == 1 then
								LLiqDispPara.volume = mDispVol
							else
								LLiqDispPara.volume = mDispVol + headVol
							end
					else
						LLiqDispPara.volume = mDispVol
					end
				end

				if dispTouch == 1 then
					LLiqDispPara.mixType = 2
				end

				LLiqTargetDisp.colNo = dispColDatas[disIdx][1]
				LLiqTargetDisp.rowNo = dispColDatas[disIdx][2]

				if n == 1 and isSameSlot == 0 then
					if currentVol > 0 and (currentVol - LLiqDispPara.volume > 0) then
						LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 1, antiDrip)
					else
						LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 1, 0)
					end
				else
					if currentVol > 0 and (currentVol - LLiqDispPara.volume > 0) then
						LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 2, antiDrip)
					else
						LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 2, 0)
					end
				end

				disIdx = disIdx + 1
				currentVol = currentVol - LLiqDispPara.volume

				if dispTouch == 1 then
					LIQ_TOUCHTIP(piptId, LLiqTargetDisp, dispTchPara)
				end
			end

			isLastInfiDisped = 0
			if setInfiDisp == 1 then
				if infiVol > 0 then
					LLiqDispParaInfi.volume = headVol + infiVol
					if isSameSlot == 1 then
						LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi, 2)
					else
						LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi, 1)
					end
					currentVol = currentVol - LLiqDispParaInfi.volume
				end
			else
				if isPickReuTip == 0 then
					LIQ_DROPTIP(piptId)
				end
			end
		end
	else -- once asp and dispCnt disp
		if isPickReuTip == 1 then
			local lastTipCnt, _, __ = LIQ_GETPIPTINFO(piptId)
			if lastTipCnt ~= 0 then
				LIQ_DROPTIP(piptId)
			end
			LIQ_PICKUPREUTIP(piptId, tipType, pickCol, pickRow, tipCnt, reuRackSlotLoc)
		else
			LIQ_TRANSFER_PICKUPTIP(piptId, tipType, tipCnt, tipRackTypeId)
		end

		if aspMix == 1 then
			LIQ_TRANSFER_MIX(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, LLiqTargetAsp, headVol, 1, isSameSlot, 1, 0, 0)
		end

		if headVol > 0 then
			LLiqAirGParaH.volume = headVol
			if aspMix == 1 then
				LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH, 2)
			else
				LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH, 1)
			end
		end

		local isAspToZHome = 1
		if aspMix == 1 then
			isAspToZHome = 2
		end

		LLiqAspPara.volume = otherVol + mDispVol * dispCnt +  infiVol
		if otherVol > 0 then
			LLiqAspPara.mixType = 2
			LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara, isAspToZHome)
			LLiqAspPara.mixType = 0
		else
			if aspTouch == 1 then
				LLiqAspPara.mixType = 2
			end
			LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara, isAspToZHome)
		end

		currentVol = currentVol + LLiqAspPara.volume

		if otherVol > 0 then
			LLiqDispParaOther.volume = otherVol
			LIQ_DISPENSE(piptId, LLiqTargetDispOthVol, LLiqDispParaOther, 2)
			currentVol = currentVol - otherVol
		end

		if aspTouch == 1 then
			LIQ_TOUCHTIP(piptId, LLiqTargetAsp, aspTchPara)
		end

		if tailVol > 0 then
			LLiqAirGParaT.volume = tailVol
			if isSameSlot == 1 then
				LIQ_AIRGAPTL(piptId, LLiqTargetAspAirTail, LLiqAirGParaT, 2, antiDrip)
			else
				LIQ_AIRGAPTL(piptId, LLiqTargetAspAirTail, LLiqAirGParaT, 1, antiDrip)
			end

			currentVol = currentVol + tailVol
		end

		for k = 1, dispCnt do
			if dispCnt == 1 then
				if setInfiDisp == 1 then
					LLiqDispPara.volume = mDispVol + tailVol
				else
					LLiqDispPara.volume = mDispVol + tailVol + headVol
				end
			else
				if k == 1 then
					LLiqDispPara.volume = mDispVol + tailVol
					elseif k == dispCnt then
						if setInfiDisp == 1 then
							LLiqDispPara.volume = mDispVol
						else
							LLiqDispPara.volume = mDispVol + headVol
						end
				else
					LLiqDispPara.volume = mDispVol
				end
			end

			if dispTouch == 1 then
				LLiqDispPara.mixType = 2
			end

			LLiqTargetDisp.colNo = dispColDatas[k][1]
			LLiqTargetDisp.rowNo = dispColDatas[k][2]

			if k == 1 and isSameSlot == 0 then
				if currentVol > 0 and (currentVol - LLiqDispPara.volume > 0) then
					LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 1, antiDrip)
				else
					LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 1, 0)
				end
			else
				if currentVol > 0 and (currentVol - LLiqDispPara.volume > 0) then
					LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 2, antiDrip)
				else
					LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara, 2, 0)
				end
			end

			currentVol = currentVol - LLiqDispPara.volume

			if dispTouch == 1 then
				LIQ_TOUCHTIP(piptId, LLiqTargetDisp, dispTchPara)
			end
		end

		if setInfiDisp == 1 then
			if infiVol > 0 then
				LLiqDispParaInfi.volume = headVol + infiVol
				if isSameSlot == 1 then
					LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi, 2)
				else
					LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi, 1)
				end
				currentVol = currentVol - LLiqDispParaInfi.volume
			end
		else
			if isPickReuTip == 0 then
				LIQ_DROPTIP(piptId)
			end
		end
	end

	if setInfiDisp == 1 and isDropTip == 1 and isPickReuTip == 0 then
		LIQ_DROPTIP(piptId)
	end

	if isPickReuTip == 1 then
		LIQ_RETTIP(piptId)
	end

	LIQ_HMPIPET(piptId)
end

-- transfer for one aspirate and multi dispense from sample data
-- local aspTchPara = MLTCHPARA(aspTchSpeed, aspTchZLoc, aspTchInHoleLoc, aspTchOpTime)
-- local dispTchPara = MLTCHPARA(dispTchSpeed, dispTchZLoc, dispTchInHoleLoc, dispTchOpTime)
-- mixOffset: the offset of aspirate zloc and dispense zloc
function LIQ_TRANSFER_MULT_SAMP(
    isDropTip, setInfiDisp,
    piptId, tipType, sampleId,
    headVol, tailVol, otherVol, infiVol, mDispVol,
    aspSlotLoc, aspColNo, aspRowNo,
    dispSlotLoc,
    airHParaSpeed,
	airTParaSpeed,
    aspParaSpeed, aspParaZLoc, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow,
    dispParaSpeed, dispParaZLoc, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow,
	aspMix, aspMixTimes, aspMixVol, aspMixSpeed,
	mixOffset,
	aspTouch, aspTchPara,
	dispTouch, dispTchPara)

	local tipMaxVol = LIQ_GETTIPVOL(tipType)
	local piptMaxVol = LIQ_GETPIPTMAXVOL(piptId)

	local maxVol
	if tipMaxVol + headVol <= piptMaxVol then
		maxVol = tipMaxVol + headVol
	elseif tipMaxVol < piptMaxVol and tipMaxVol + headVol > piptMaxVol then
		maxVol = tipMaxVol
	elseif tipMaxVol >= piptMaxVol then
		maxVol = piptMaxVol
	end

	-- if enable before aspiration mix, disable liq level detection and follow
	if aspMix == 1 then
		aspParaLevelDet = 0
		aspParaLevelFollow = 0
	end

    local LLiqTargetAspAirHead = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                                       
    local LLiqTargetAsp = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                            
    local LLiqTargetDisp = MLTARGET(dispSlotLoc, 1, 1)                            
    local LLiqTargetDispOthVol = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                     
    local LLiqTargetDispInfi = MLTARGET(aspSlotLoc, aspColNo, aspRowNo)                       

    local LLiqAirGParaH = MLAGAPPARA(headVol, airHParaSpeed, 0)                        
    local LLiqAirGParaT = MLAGAPPARA(tailVol, airTParaSpeed, 0)                        
    local LLiqAspPara = MLCONPARA(10, aspParaSpeed, aspParaZLoc, 0, aspParaDelayTime, aspParaZLiqLevel, aspParaLevelDet, aspParaLevelFollow)               
    local LLiqDispPara = MLCONPARA(10, dispParaSpeed, dispParaZLoc, 0, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow)              
    local LLiqDispParaOther = MLCONPARA(10, dispParaSpeed, dispParaZLoc, 0, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow)         
    local LLiqDispParaInfi= MLCONPARA(10, dispParaSpeed, dispParaZLoc, 0, dispParaDelayTime, dispParaZLiqLevel, dispParaLevelDet, dispParaLevelFollow)           

    local nNumDispFull_1 = IDIV(maxVol - headVol - tailVol - infiVol, mDispVol)
    local nNumDispFull_2 = IDIV(maxVol - headVol - otherVol - infiVol, mDispVol)
    local nNumDispFull = math.min(nNumDispFull_1, nNumDispFull_2)

	local typeCnt, data = LIQ_GETSAMPINFOBYPT(sampleId)

    for i = 1, typeCnt do
        local tipCnt = data[i][1][1]
        local innerArray = data[i]
        local dispCnt = #innerArray

        if setInfiDisp == 1 and i > 1 then
            LIQ_DROPTIP(piptId)
        end
        
        if dispCnt > nNumDispFull then
            local nNumAsp1 = IDIV(dispCnt, nNumDispFull)
            local nNumdisp2 = dispCnt - nNumAsp1 * nNumDispFull       
			LIQ_TRANSFER_PICKUPTIP(piptId, tipType, tipCnt)

            local disIdx = 1
            for k = 1, nNumAsp1 do
                if k > 1 and setInfiDisp == 0 then               
                    LIQ_PICKUPTIP(piptId, tipType, tipCnt)
                end

				if aspMix == 1 then
					LIQ_TRANSFER_MIX_OLD(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, LLiqTargetAsp, headVol, 1)		
				end
				
				if headVol > 0 then
                	LLiqAirGParaH.volume = headVol
                	LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH)
				end
                LLiqAspPara.volume = otherVol + nNumDispFull * mDispVol + infiVol
                LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara)
                if otherVol > 0 then
                    LLiqDispParaOther.volume = otherVol
                    LLiqDispParaOther.mixType = 3
                    LIQ_DISPENSE(piptId, LLiqTargetDispOthVol, LLiqDispParaOther)
                    LLiqDispParaOther.mixType = 0
                end

				if aspTouch == 1 then
					LIQ_TOUCHTIP(piptId, LLiqTargetAsp, aspTchPara)
				end
				
				if tailVol > 0 then
               		LLiqAirGParaT.volume = tailVol
                	LIQ_AIRGAPTL(piptId, LLiqAirGParaT)
                end

                for j = 1 , nNumDispFull do
                    local item = innerArray[disIdx]
                    if j == 1 then
                        LLiqDispPara.volume = mDispVol + tailVol
                    else
                        LLiqDispPara.volume = mDispVol
                    end
					LLiqTargetDisp.colNo = item[2]
					LLiqTargetDisp.rowNo = item[3]
                    LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara)
                    disIdx = disIdx + 1

					if dispTouch == 1 then
						LIQ_TOUCHTIP(piptId, LLiqTargetDisp, dispTchPara)
					end
				end

                if setInfiDisp == 1 then
                    if infiVol > 0 then
                        LLiqDispParaInfi.volume = headVol + infiVol
                        LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi)
                    end
                else
                    LIQ_DROPTIP(piptId)
                end
            end
            
            if nNumdisp2 > 0 then
                if setInfiDisp == 0 then
                    LIQ_PICKUPTIP(piptId, tipType, tipCnt)
                end

				if aspMix == 1 then
					LIQ_TRANSFER_MIX_OLD(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, LLiqTargetAsp, headVol, 1)				
				end
				
				if headVol > 0 then
                	LLiqAirGParaH.volume = headVol
                	LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH)
				end
                LLiqAspPara.volume = otherVol + nNumdisp2 * mDispVol + infiVol
                LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara)
                if otherVol > 0 then
                    LLiqDispParaOther.volume = otherVol
                    LLiqDispParaOther.mixType = 3
                    LIQ_DISPENSE(piptId, LLiqTargetDispOthVol, LLiqDispParaOther)
                    LLiqDispParaOther.mixType = 0
                end

				if aspTouch == 1 then
					LIQ_TOUCHTIP(piptId, LLiqTargetAsp, aspTchPara)
				end
				
				if tailVol > 0 then
                	LLiqAirGParaT.volume = tailVol
                	LIQ_AIRGAPTL(piptId, LLiqAirGParaT)
                end

                for n = 1 , nNumdisp2  do
                    local item = innerArray[disIdx]
                    if n == 1 then
                        LLiqDispPara.volume = mDispVol + tailVol
                    else
                        LLiqDispPara.volume = mDispVol
                    end
					LLiqTargetDisp.colNo = item[2]
					LLiqTargetDisp.rowNo = item[3]
                    LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara)
                    disIdx = disIdx + 1

					if dispTouch == 1 then
						LIQ_TOUCHTIP(piptId, LLiqTargetDisp, dispTchPara)
					end

                end

                if setInfiDisp == 1 then
                    if infiVol > 0 then
                        LLiqDispParaInfi.volume = headVol + infiVol
                        LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi)
                    end
                else
                    LIQ_DROPTIP(piptId)
                end
            end
        else
			LIQ_TRANSFER_PICKUPTIP(piptId, tipType, tipCnt)

			if aspMix == 1 then
				LIQ_TRANSFER_MIX_OLD(piptId, aspMixTimes, aspMixVol, aspMixSpeed, mixOffset, aspParaZLoc, aspParaDelayTime, dispParaDelayTime, aspParaZLiqLevel, LLiqTargetAsp, headVol, 1)				
			end

			if headVol > 0 then
            	LLiqAirGParaH.volume = headVol
            	LIQ_AIRGAPHD(piptId, LLiqTargetAspAirHead, LLiqAirGParaH)
			end
				LLiqAspPara.volume = otherVol + mDispVol * dispCnt +  infiVol
            LIQ_ASPIRATE(piptId, LLiqTargetAsp, LLiqAspPara)
            if otherVol > 0 then
                LLiqDispParaOther.volume = otherVol
                LLiqDispParaOther.mixType = 3
                LIQ_DISPENSE(piptId, LLiqTargetDispOthVol, LLiqDispParaOther)
                LLiqDispParaOther.mixType = 0
            end

			if aspTouch == 1 then
				LIQ_TOUCHTIP(piptId, LLiqTargetAsp, aspTchPara)
			end

			if tailVol > 0 then
            	LLiqAirGParaT.volume = tailVol
            	LIQ_AIRGAPTL(piptId, LLiqAirGParaT)
			end
			
            for k = 1, dispCnt do
                local item = innerArray[k]   
                if k == 1 then
                    LLiqDispPara.volume = mDispVol + tailVol
                else
                    LLiqDispPara.volume = mDispVol
                end
				LLiqTargetDisp.colNo = item[2]
				LLiqTargetDisp.rowNo = item[3]
                LIQ_DISPENSE(piptId, LLiqTargetDisp, LLiqDispPara)

				if dispTouch == 1 then
					LIQ_TOUCHTIP(piptId, LLiqTargetDisp, dispTchPara)
				end
            end

            if setInfiDisp == 1 then
                if infiVol > 0 then
                    LLiqDispParaInfi.volume = headVol + infiVol
                    LIQ_DISPENSE(piptId, LLiqTargetDispInfi, LLiqDispParaInfi)
                end
            else
                LIQ_DROPTIP(piptId)
            end
        end
    end

	if setInfiDisp == 1 and isDropTip == 1 then
		LIQ_DROPTIP(piptId)
	end

	LIQ_HMPIPET(piptId)
end

-- local mixColDatas = {{1, 1}, {1, 4}, {1, 5}}
function LIQ_MIX(
	piptId, 
	mixTimes, mixVol, mixSpeed, mixZLiqLevel,
	aspZLoc, aspDelayTime,
 	dispZLoc, dispDelayTime,
	touch, touchSpeed, touchZLoc, touchInHoleLoc, touchOpTime,
	isSaveFinalVol,
	slotLoc, mixColDatas)

	if mixTimes < 1 then
		GOTOERROR("mixTimes should be greater than 0")
		return
	end

	-- todo
end
