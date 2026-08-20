local main=GModule.UIModule:FindOpenedView(GViewId.MAIN_FRAME)
local btn=main:GetBtnWorldSearchObj()
local lines={"BTN\t"..tostring(btn),"TYPE\t"..type(btn)}
local function add(owner,label)
 if type(owner)~="table" then return end
 for k,v in pairs(owner) do
  local n=string.lower(tostring(k))
  if type(v)=="function" or string.find(n,"click",1,true) or string.find(n,"event",1,true) or string.find(n,"on",1,true) or string.find(n,"button",1,true) then
   lines[#lines+1]=table.concat({label,tostring(k),type(v),tostring(v)},"\t")
  end
 end
end
add(btn,"BTN_FIELD")
if type(btn)=="userdata" then
 for _,key in ipairs({"onClick","gameObject","transform","m_onClick","m_GameObject","name"}) do local ok,v=pcall(function() return btn[key] end); lines[#lines+1]=table.concat({"INDEX",key,tostring(ok),type(v),tostring(v)},"\t") end
end
return table.concat(lines,"\n")
