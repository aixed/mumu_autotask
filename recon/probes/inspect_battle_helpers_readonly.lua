local lines = {}

local function add(...)
    local parts = {}
    for index = 1, select("#", ...) do
        parts[#parts + 1] = tostring(select(index, ...))
    end
    lines[#lines + 1] = table.concat(parts, "\t")
end

local function safe(obj, key)
    local ok, value = pcall(function() return obj and obj[key] end)
    if ok then
        return value
    end
    return nil
end

local function dump_functions(label, tbl)
    if type(tbl) ~= "table" then
        add("GROUP", label, type(tbl))
        return
    end
    local names = {}
    for key, value in pairs(tbl) do
        if type(value) == "function" then
            names[#names + 1] = tostring(key)
        end
    end
    table.sort(names)
    for _, name in ipairs(names) do
        add("FUNC", label, name)
    end
end

add("GVIEW_RADAR", tostring(safe(GViewId, "RADAR")))
add("GVIEW_RADAR_EXECUTE", tostring(safe(GViewId, "RADAR_QUEST_EXECUTE")))
add("GVIEW_BATTLE", tostring(safe(GViewId, "BATTLE")))
dump_functions("RadarCtrl", safe(safe(GCtrl, "RadarCtrl"), "class"))
dump_functions("HeroCtrl", safe(safe(GCtrl, "HeroCtrl"), "class"))
dump_functions("HeroDataCtrl", safe(safe(GCtrl, "HeroDataCtrl"), "class"))
dump_functions("PveCtrl", safe(safe(GCtrl, "PveCtrl"), "class"))
dump_functions("BattleCtrl", safe(safe(GCtrl, "BattleCtrl"), "class"))
dump_functions("FormationHelper", safe(GHelper, "FormationHelper"))
dump_functions("HeroHelper", safe(GHelper, "HeroHelper"))
dump_functions("BattleHelper", safe(GHelper, "BattleHelper"))
dump_functions("RadarHelper", safe(GHelper, "RadarHelper"))
dump_functions("PveHelper", safe(GHelper, "PveHelper"))
add("END")
return table.concat(lines, "\n"):sub(1, 15000)
