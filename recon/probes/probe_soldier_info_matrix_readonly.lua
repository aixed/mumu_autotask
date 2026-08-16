local expedition = GHelper.ExpeditionHelper
local target_id = 427
local quest = GCtrl.RadarCtrl:GetQuestDataMap()[target_id]
local config = quest and quest:GetQuestConfig() or nil
local monster = config and config.condition or 0
local extra_values = {
    { "nil", nil },
    { "event", { event_id = target_id } },
    { "monster", { event_id = target_id, monster_id = monster } },
}
local march_values = {
    { "atk_monster", WorldMapDefine.march_type.atk_monster },
    { "atk_monster_auto", WorldMapDefine.march_type.atk_monster_auto },
    { "transaction_slg", WorldMapDefine.march_type.transaction_slg },
    { "world_attack_mapobj", GHelper.WorldMarchHelper.GetAttackMarchType(WorldMapDefine.mapobj_type.map_monster) },
}
local whole_values = {
    { "nil", nil },
    { "false", false },
    { "true", true },
}

local function count(value)
    if type(value) ~= "table" then
        return -1
    end
    local result = 0
    for _ in pairs(value) do
        result = result + 1
    end
    return result
end

local lines = {}
for _, march_pair in ipairs(march_values) do
    for _, whole_pair in ipairs(whole_values) do
        for _, extra_pair in ipairs(extra_values) do
            local ok, first, second, third, fourth = pcall(
                expedition.GetSoldierInfoByMarchType,
                march_pair[2],
                0,
                whole_pair[2],
                extra_pair[2],
                nil
            )
            lines[#lines + 1] = table.concat({
                "TRY",
                march_pair[1] .. "=" .. tostring(march_pair[2]),
                "whole=" .. whole_pair[1],
                "extra=" .. extra_pair[1],
                ok and "OK" or "ERR",
                ok and type(first) or tostring(first),
                ok and tostring(count(first)) or "",
                ok and type(second) or "",
                ok and type(third) or "",
                ok and type(fourth) or "",
            }, "\t")
        end
    end
end
return table.concat(lines, "\n")
