function mod002Init()
  SETLUAAPPSTATUS(0)
  --TargetDeviceId
  SETSYSINVARI(0,0)
  --Pos X
  SETSYSINVARI(1,0)
  --Pos Y
  SETSYSINVARI(2,0)
  --Pos Z
  SETSYSINVARI(3,0)
  --RobotMoveType
  SETSYSINVARI(4,0)
  --RobotObjType
  SETSYSINVARI(5,0)
  --PointInUpperComputer
  SETSYSINVARI(6,0)
  --MoveMode
  SETSYSINVARI(7,0)
  --Reset system output variables
  RESETSYSOUTVARI()
  SETLUAAPPSTATUS(1)
  PRINT("Init Successful!")
end--functionend
--Fileinfomation:
