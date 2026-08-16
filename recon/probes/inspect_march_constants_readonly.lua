local function safe(label, fn)
    local ok, value = pcall(fn)
    if ok then
        return label .. "=" .. tostring(value) .. ":" .. type(value)
    end
    return label .. "=ERR:" .. tostring(value)
end

local lines = {}
lines[#lines + 1] = safe("march_type.transaction_slg", function()
    return WorldMapDefine.march_type.transaction_slg
end)
lines[#lines + 1] = safe("mapobj_type.map_monster", function()
    return WorldMapDefine.mapobj_type.map_monster
end)
lines[#lines + 1] = safe("MARCH_MAP_TYPE.NORMAL", function()
    return GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
end)
lines[#lines + 1] = safe("Expedition.Check_Monster", function()
    return GHelper.ExpeditionHelper.Check_Monster
end)
lines[#lines + 1] = safe("World.GetAttackMarchType", function()
    return GHelper.WorldMarchHelper.GetAttackMarchType(WorldMapDefine.mapobj_type.map_monster)
end)
lines[#lines + 1] = safe("city_pos", function()
    local x, y = GCtrl.WorldPlayerCtrl:GetPlayerCityPos()
    return tostring(x) .. "," .. tostring(y)
end)
lines[#lines + 1] = safe("player_kid", function()
    return GCtrl.WorldPlayerCtrl:GetPlayerCityKid()
end)

for key, value in pairs(WorldMapDefine.march_type) do
    if tostring(key):find("monster")
        or tostring(key):find("transaction")
        or tostring(value):find("monster")
        or tostring(value):find("transaction") then
        lines[#lines + 1] = "march_type_entry=" .. tostring(key) .. ":" .. tostring(value)
    end
end

return table.concat(lines, "\n")
