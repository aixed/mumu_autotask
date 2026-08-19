local view = GModule.UIModule:FindOpenedView(GViewId.WORLD_SEARCH_OBJ)
if type(view) ~= "table" then
    return "VIEW\tmissing"
end
local point = view._prePoint
return table.concat({
    "RESULT",
    tostring(view._selectedObjType),
    tostring(type(point) == "table" and point.x or nil),
    tostring(type(point) == "table" and point.y or nil),
    tostring(view._kid),
    tostring(type(view.objLvMap) == "table" and view.objLvMap[1] or nil),
}, "\t")
