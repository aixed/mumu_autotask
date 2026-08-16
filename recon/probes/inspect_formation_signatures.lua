local targets = {
    {"EXPEDITION", "GetFormationHeroData", require("game.helper.ExpeditionHelper")},
    {"EXPEDITION", "GetFormationNumLimit", require("game.helper.ExpeditionHelper")},
    {"EXPEDITION", "GetFormationPrefabs", require("game.helper.ExpeditionHelper")},
    {"EXPEDITION", "GetFormationSoldierData", require("game.helper.ExpeditionHelper")},
    {"EXPEDITION", "GetRecommendedHeroList", require("game.helper.ExpeditionHelper")},
    {"EXPEDITION", "GetSoldierInfoByMarchType", require("game.helper.ExpeditionHelper")},
    {"EXPEDITION", "GetTroopLimit", require("game.helper.ExpeditionHelper")},
    {"FORMATION", "DealWithExpeditionInfo", require("game.helper.FormationHelper")},
    {"FORMATION", "GetAverageSoldierList", require("game.helper.FormationHelper")},
    {"FORMATION", "GetFormationHeroData", require("game.helper.FormationHelper")},
    {"FORMATION", "GetFormationSoldierData", require("game.helper.FormationHelper")},
    {"FORMATION", "GetSoldierDefaultSelection", require("game.helper.FormationHelper")},
    {"WORLD", "GetAttackMarchType", require("game.helper.WorldMarchHelper")},
    {"WORLD", "RequestMarchStartOff", require("game.helper.WorldMarchHelper")},
}

local function module_name(value)
    for name, loaded in pairs(package.loaded) do
        if loaded == value then
            return tostring(name)
        end
    end
    return ""
end

local lines = {}
for _, target in ipairs(targets) do
    local group, name, owner = target[1], target[2], target[3]
    local func = assert(owner[name], group .. "." .. name .. " unavailable")
    local info = require("jit.util").funcinfo(func)
    lines[#lines + 1] = table.concat({
        "FUNC",
        group,
        name,
        tostring(info.params or ""),
        tostring(info.bytecodes or ""),
        tostring(info.upvalues or ""),
        tostring(#string.dump(func)),
    }, "\t")
    for index = 1, 16 do
        local upvalue_name, value = debug.getupvalue(func, index)
        if upvalue_name == nil then
            break
        end
        lines[#lines + 1] = table.concat({
            "UPVALUE",
            group,
            name,
            tostring(index),
            tostring(upvalue_name),
            type(value),
            module_name(value),
        }, "\t")
    end
end
return table.concat(lines, "\n")
