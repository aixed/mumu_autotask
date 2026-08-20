local main=GModule.UIModule:FindOpenedView(GViewId.MAIN_FRAME)
local lines={}
local names={"GetBtnWorldSearchObj","GetHomeEntrance","GetBottomBtnGroupBattle","GetRadarBtn","GetOverviewBtn","GetLawBtn","GetBtnAllianceMobilizationObj","GetBtnSupremacySearchObj","GetMineWarSearchBtn"}
for _,name in ipairs(names) do
 local ok,v=pcall(main[name],main)
 lines[#lines+1]=table.concat({name,tostring(ok),type(v),tostring(v)},"\t")
 if ok and v~=nil then
  for _,key in ipairs({"name","onClick","gameObject","transform","m_onClick","m_GameObject"}) do local iok,x=pcall(function() return v[key] end); lines[#lines+1]=table.concat({name,key,tostring(iok),type(x),tostring(x)},"\t") end
 end
end
return table.concat(lines,"\n")
