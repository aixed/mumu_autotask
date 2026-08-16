local expedition = require("game.helper.ExpeditionHelper")
local targets = {
    {"Expedition.GetFormationHeroData", expedition.GetFormationHeroData},
    {"Expedition.GetFormationNumLimit", expedition.GetFormationNumLimit},
    {"Expedition.GetFormationSoldierData", expedition.GetFormationSoldierData},
    {"Expedition.GetRecommendedHeroList", expedition.GetRecommendedHeroList},
    {"Expedition.GetSoldierInfoByMarchType", expedition.GetSoldierInfoByMarchType},
    {"Expedition.GetTroopLimit", expedition.GetTroopLimit},
}

local function hex(value)
    return (value:gsub(".", function(character)
        return string.format("%02x", string.byte(character))
    end))
end

local lines = {}
for _, target in ipairs(targets) do
    lines[#lines + 1] = target[1] .. "\t" .. hex(string.dump(assert(target[2])))
end
return table.concat(lines, "\n")
