local function fail(message)
    error("probe: " .. message, 0)
end

local function count(value)
    if type(value) ~= "table" then
        return -1
    end
    local total = 0
    for _ in pairs(value) do
        total = total + 1
    end
    return total
end

local function sorted_numeric_keys(value)
    local keys = {}
    if type(value) ~= "table" then
        return keys
    end
    for key, _ in pairs(value) do
        if type(key) == "number" then
            keys[#keys + 1] = key
        end
    end
    table.sort(keys)
    return keys
end

local function first_target()
    local quest_map = GCtrl.RadarCtrl:GetQuestDataMap()
    local best = nil
    for runtime_id, quest in pairs(quest_map) do
        if type(quest) == "table"
            and quest:GetQuestType() == 1
            and quest:IsShowInWorld()
            and quest._status == 1
            and quest:GetValidTime() > 30 then
            local quality = quest:GetQuality()
            if quality == 4 or quality == 5 or quality == 3 or quality == 2 then
                local config = quest:GetQuestConfig()
                if type(config) == "table" then
                    local candidate = {
                        runtime_id = runtime_id,
                        quest = quest,
                        config = config,
                        quality = quality,
                        expires_at = quest._expireTime or 0,
                    }
                    if best == nil
                        or candidate.quality < best.quality
                        or (
                            candidate.quality == best.quality
                            and candidate.expires_at < best.expires_at
                        )
                        or (
                            candidate.quality == best.quality
                            and candidate.expires_at == best.expires_at
                            and candidate.runtime_id < best.runtime_id
                        ) then
                        best = candidate
                    end
                end
            end
        end
    end
    if best == nil then
        fail("no available target")
    end
    return best
end

local target = first_target()
local expedition = GHelper.ExpeditionHelper
local formation = GHelper.FormationHelper
local march_map_type = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
local march_type = WorldMapDefine.march_type.transaction_slg
local map_object_type = WorldMapDefine.mapobj_type.map_monster
local formation_march_type = GHelper.WorldMarchHelper.GetAttackMarchType(
    map_object_type
)
local extra = { event_id = target.runtime_id }
local target_id = target.config.condition
local hero_list = expedition.GetRecommendedHeroList(
    false,
    false,
    formation_march_type,
    target_id,
    march_map_type,
    extra
)
local fight_type = GDefine.HeroDefine.HeroAttrType.SLG
local formation_limit = expedition.GetTroopLimit(
    march_map_type,
    hero_list,
    fight_type,
    extra
)
local yields = expedition.GetResourceYields(march_type, nil)
local open_params = {
    marchMapType = march_map_type,
    marchType = march_type,
    formationNumLimt = formation_limit,
    targetId = target_id,
    yields = yields,
    isAttack = false,
}
local soldier_list = expedition.GetSoldierInfoByMarchType(
    formation_march_type,
    0,
    false,
    open_params,
    nil
)
local averaged = formation.GetAverageSoldierList(
    march_map_type,
    soldier_list,
    formation_limit,
    false,
    extra
)
local hero_id, soldier = formation.DealWithExpeditionInfo(hero_list, averaged)
local world_x, world_y = target.quest:GetWorldPos()
local selected = 0
for _, item in ipairs(averaged) do
    if type(item) == "table" and type(item.selectNum) == "number" then
        selected = selected + item.selectNum
    end
end

local lines = {
    "DIRECT_PAYLOAD",
    "target=" .. tostring(target.runtime_id),
    "quality=" .. tostring(target.quality),
    "xy=" .. tostring(world_x) .. "," .. tostring(world_y),
    "monster=" .. tostring(target_id),
    "march_map_type=" .. tostring(march_map_type),
    "march_type=" .. tostring(march_type),
    "formation_march_type=" .. tostring(formation_march_type),
    "fight_type=" .. tostring(fight_type),
    "yields=" .. tostring(yields),
    "limit=" .. tostring(formation_limit),
    "hero_list_count=" .. tostring(count(hero_list)),
    "soldier_list_count=" .. tostring(count(soldier_list)),
    "averaged_count=" .. tostring(count(averaged)),
    "selected=" .. tostring(selected),
    "hero_id_count=" .. tostring(count(hero_id)),
    "soldier_count=" .. tostring(count(soldier)),
}
for _, key in ipairs(sorted_numeric_keys(hero_id)) do
    lines[#lines + 1] = "hero_id." .. tostring(key) .. "=" .. tostring(hero_id[key])
end
for _, key in ipairs(sorted_numeric_keys(soldier)) do
    lines[#lines + 1] = "soldier." .. tostring(key) .. "=" .. tostring(soldier[key])
end
return table.concat(lines, "\n")
