function mod001Socket1()
  mod004Phome()
  mod002Init()
  while(1==1)do
    GETSYSINVARI()
    if(SYSINVAR0~=0 and SYSINVAR1~=0 and SYSINVAR2~=0)then
    if(SYSINVAR3~=0 and SYSINVAR4~=0 and SYSINVAR5~=0)then
    if(SYSINVAR0==1)then
      if(SYSINVAR4==1)then
        mod_Pick1()
      elseif(SYSINVAR4==2)then
        mod_Place1()
      end
    elseif(SYSINVAR0==2)then
      if(SYSINVAR4==1)then
        mod_Pick2()
      elseif(SYSINVAR4==2)then
        mod_Place2()
      end
    end
  else
    PRINT("Signal Error")
    break
  end
  end
  TIMER(10)
  end
end--functionend
--Fileinfomation:
