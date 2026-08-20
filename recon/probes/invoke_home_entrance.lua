local main=GModule.UIModule:FindOpenedView(GViewId.MAIN_FRAME)
if type(main)~="table" then error("MAIN_FRAME missing",0) end
local btn=main:GetHomeEntrance()
if btn==nil or btn.onClick==nil then error("HomeEntrance button unavailable",0) end
btn.onClick:Invoke()
return "HOME_ENTRANCE_INVOKED\t1\nEND\t1"
