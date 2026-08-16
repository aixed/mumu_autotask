local groups = {
    {"FORMATION", require("game.helper.FormationHelper")},
    {"EXPEDITION", require("game.helper.ExpeditionHelper")},
    {"WORLD", require("game.helper.WorldMarchHelper")},
    {"MARCH_CTRL", assert(GCtrl.WorldMarchCtrl.class, "WorldMarchCtrl class unavailable")},
    {"RADAR_CTRL", assert(GCtrl.RadarCtrl.class, "RadarCtrl class unavailable")},
}

local lines = {}
for _, group in ipairs(groups) do
    for key, value in pairs(group[2]) do
        if type(value) == "function" then
            lines[#lines + 1] = group[1] .. "\t" .. tostring(key)
        end
    end
end

for name, value in pairs(package.loaded) do
    local encoded = tostring(name)
    if type(value) == "table" and encoded:match("[Uu][Ii].*[Mm]odule") then
        lines[#lines + 1] = "LOADED\t" .. encoded
    end
end

table.sort(lines)
return table.concat(lines, "\n"):sub(1, 15000)
