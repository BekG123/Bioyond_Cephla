function mod004Phome()
  while(1==1)do
    --LJ1--Phome point
    local LJ1=MJOINT(100,0,0,0,0,0,0,0,0,0,0,0)
    --LJ2--Actual pose of the robot
    local LJ2=GETJOINTS()
    local LVAR1=0
    LVAR1=JOINTS4EQUAL(LJ1,LJ2,5)
    if(LVAR1>=1)then
      PRINT("The Robot at home point")
      break
    else
      PRINT("The Robot is not at home point")
      MOVABSJ(LJ1,50,0)
    end
  end
end--functionend
--Fileinfomation:
