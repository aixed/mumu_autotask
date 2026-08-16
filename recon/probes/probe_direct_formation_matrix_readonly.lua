local TARGET_RUNTIME_ID = 427
local quest = GCtrl.RadarCtrl:GetQuestDataMap()[TARGET_RUNTIME_ID]
local config = quest and quest:GetQuestConfig() or nil
if not config then
    error("target unavailable", 0)
end

local expedition = GHelper.ExpeditionHelper
local formation = GHelper.FormationHelper
local march_map_type = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
local march_type = WorldMapDefine.march_type.transaction_slg
local computed_march_type = GHelper.WorldMarchHelper.GetAttackMarchType(
    WorldMapDefine.mapobj_type.map_monster
)
local target_id = config.condition
local extra = { event_id = TARGET_RUNTIME_ID }
local fight_type = GDefine.HeroDefine.HeroAttrType.SLG
local yields = expedition.GetResourceYields(march_type, nil)

local hero_list = expedition.GetRecommendedHeroList(
    false,
    false,
    computed_march_type,
    target_id,
    march_map_type,
    extra
)

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

local limit_inputs = {
    { "nil_nil", nil, nil },
    { "heroes_nil", hero_list, nil },
    { "heroes_slg", hero_list, fight_type },
}

local lines = {
    "hero_type=" .. type(hero_list),
    "hero_count=" .. tostring(count(hero_list)),
    "fight_type=" .. tostring(fight_type),
    "yields=" .. tostring(yields),
}

for _, limit_input in ipairs(limit_inputs) do
    local ok_limit, limit = pcall(
        expedition.GetTroopLimit,
        march_map_type,
        limit_input[2],
        limit_input[3],
        extra
    )
    lines[#lines + 1] = table.concat({
        "LIMIT",
        limit_input[1],
        ok_limit and "OK" or "ERR",
        tostring(limit),
        type(limit),
    }, "\t")
    if ok_limit and type(limit) == "number" and limit > 0 then
        local open_params = {
            marchMapType = march_map_type,
            marchType = march_type,
            formationNumLimt = limit,
            targetId = target_id,
            yields = yields,
            isAttack = false,
        }
        local ok_soldiers, soldiers = pcall(
            expedition.GetSoldierInfoByMarchType,
            computed_march_type,
            0,
            false,
            open_params,
            nil
        )
        lines[#lines + 1] = table.concat({
            "SOLDIERS",
            limit_input[1],
            ok_soldiers and "OK" or "ERR",
            ok_soldiers and type(soldiers) or tostring(soldiers),
            ok_soldiers and tostring(count(soldiers)) or "",
        }, "\t")
        if ok_soldiers then
            local ok_average, averaged = pcall(
                formation.GetAverageSoldierList,
                march_map_type,
                soldiers,
                limit,
                false,
                extra
            )
            lines[#lines + 1] = table.concat({
                "AVERAGE",
                limit_input[1],
                ok_average and "OK" or "ERR",
                ok_average and type(averaged) or tostring(averaged),
                ok_average and tostring(count(averaged)) or "",
            }, "\t")
            if ok_average then
                local selected = 0
                for _, item in ipairs(averaged) do
                    if type(item) == "table" and type(item.selectNum) == "number" then
                        selected = selected + item.selectNum
                    end
                end
                local ok_deal, hero_id, soldier = pcall(
                    formation.DealWithExpeditionInfo,
                    hero_list,
                    averaged
                )
                lines[#lines + 1] = table.concat({
                    "DEAL",
                    limit_input[1],
                    ok_deal and "OK" or "ERR",
                    ok_deal and type(hero_id) or tostring(hero_id),
                    ok_deal and tostring(count(hero_id)) or "",
                    ok_deal and type(soldier) or "",
                    ok_deal and tostring(count(soldier)) or "",
                    "selected=" .. tostring(selected),
                }, "\t")
            end
        end
    end
end

return table.concat(lines, "\n")
