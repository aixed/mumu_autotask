local view = GModule.UIModule:FindOpenedView(GViewId.MAIN_FRAME)
local lines={"VIEW\t"..tostring(view)}
if type(view)=="table" then
  for k,v in pairs(view) do
    local n=string.lower(tostring(k))
    if type(v)=="function" or string.find(n,"world",1,true) or string.find(n,"map",1,true) or string.find(n,"btn",1,true) or string.find(n,"click",1,true) or string.find(n,"field",1,true) then
      lines[#lines+1]=table.concat({"FIELD",tostring(k),type(v),tostring(v)},"\t")
    end
  end
  if type(view.class)=="table" then
    for k,v in pairs(view.class) do
      local n=string.lower(tostring(k))
      if type(v)=="function" or string.find(n,"world",1,true) or string.find(n,"map",1,true) or string.find(n,"btn",1,true) or string.find(n,"click",1,true) then
        lines[#lines+1]=table.concat({"CLASS",tostring(k),type(v),tostring(v)},"\t")
      end
    end
  end
end
return table.concat(lines,"\n")
