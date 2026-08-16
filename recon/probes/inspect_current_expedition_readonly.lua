local lines = {}
local function add(...)
    local parts = {}
    for index = 1, select("#", ...) do
        parts[#parts + 1] = tostring(select(index, ...))
    end
    lines[#lines + 1] = table.concat(parts, "\t")
end

local view = nil
if type(GModule) == "table" and type(GModule.UIModule) == "table"
    and type(GViewId) == "table" and GViewId.EXPEDITION ~= nil then
    local ok, result = pcall(GModule.UIModule.FindOpenedView, GModule.UIModule, GViewId.EXPEDITION)
    if ok then view = result end
end
add("EXPEDITION", type(view), tostring(view))
if type(view) == "table" then
    add("IS_LOADED", pcall(function() return view:IsLoaded() end))
    add("IS_OPEN", pcall(function() return view:IsOpen() end))
    add("MARCH", view.marchMapType, view.marchType, view.mapObjType)
    if type(view.pointEnd) == "table" then
        add("POINT_END", view.pointEnd.x, view.pointEnd.y)
    end
    if type(view.extra) == "table" then
        add("EXTRA_EVENT", view.extra.event_id)
    end
    add("TARGET", view.targetId, "STAMINA", view.stamina)
    add("HERO_LIST", type(view.showHeroList), tostring(view.showHeroList))
    add("SOLDIER_LIST", type(view.soldierList), tostring(view.soldierList))
    add("FORMATION_LIMIT", view.formationNumLimt)
    add("ALL_STAMINA", view.allStamina)
end
add("END")
return table.concat(lines, "\n")
