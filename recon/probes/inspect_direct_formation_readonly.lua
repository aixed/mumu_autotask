local TARGET_RUNTIME_ID = 427

local function fail(message)
    error("probe: " .. message, 0)
end

local function count_table(value)
    if type(value) ~= "table" then
        return -1
    end
    local count = 0
    for _ in pairs(value) do
        count = count + 1
    end
    return count
end

local function integer(value, label)
    if type(value) ~= "number" or value ~= math.floor(value) then
        fail(label .. " is not an integer")
    end
    return value
end

local quest_map = GCtrl.RadarCtrl:GetQuestDataMap()
local quest = quest_map[TARGET_RUNTIME_ID]
if type(quest) ~= "table" then
    fail("target is unavailable")
end
local config = quest:GetQuestConfig()
if type(config) ~= "table" then
    fail("target config is unavailable")
end
local world_x, world_y = quest:GetWorldPos()
world_x = integer(world_x, "world x")
world_y = integer(world_y, "world y")

local expedition = GHelper.ExpeditionHelper
local formation = GHelper.FormationHelper
local march_map_type = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
local march_type = WorldMapDefine.march_type.transaction_slg
local extra = { event_id = TARGET_RUNTIME_ID }
local is_whole = false
local is_guide = false
local is_attack = false
local target_id = config.condition

local computed_march_type = GHelper.WorldMarchHelper.GetAttackMarchType(
    WorldMapDefine.mapobj_type.map_monster
)

local hero_list = expedition.GetRecommendedHeroList(
    is_whole,
    is_guide,
    computed_march_type,
    target_id,
    march_map_type,
    extra
)
local soldier_list = expedition.GetSoldierInfoByMarchType(
    computed_march_type,
    0,
    is_whole,
    extra,
    nil
)
local limit = expedition.GetTroopLimit(
    march_map_type,
    computed_march_type,
    target_id,
    extra
)
if type(limit) ~= "number" or limit <= 0 then
    limit = 1
end
local averaged = formation.GetAverageSoldierList(
    march_map_type,
    soldier_list,
    limit,
    false,
    extra
)
local hero_id, soldier = formation.DealWithExpeditionInfo(hero_list, averaged)

local selected = 0
if type(averaged) == "table" then
    for _, item in ipairs(averaged) do
        if type(item) == "table" and type(item.selectNum) == "number" then
            selected = selected + item.selectNum
        end
    end
end

return table.concat({
    "DIRECT_FORMATION",
    "target=" .. tostring(TARGET_RUNTIME_ID),
    "xy=" .. tostring(world_x) .. "," .. tostring(world_y),
    "monster=" .. tostring(target_id),
    "march_map_type=" .. tostring(march_map_type),
    "march_type=" .. tostring(march_type),
    "computed_march_type=" .. tostring(computed_march_type),
    "hero_list_type=" .. type(hero_list),
    "hero_count=" .. tostring(count_table(hero_list)),
    "soldier_list_type=" .. type(soldier_list),
    "soldier_count=" .. tostring(count_table(soldier_list)),
    "limit=" .. tostring(limit),
    "selected=" .. tostring(selected),
    "hero_id_type=" .. type(hero_id),
    "hero_id_count=" .. tostring(count_table(hero_id)),
    "soldier_type=" .. type(soldier),
    "soldier_count=" .. tostring(count_table(soldier)),
}, "\n")
