local formation = require("game.helper.FormationHelper")
local targets = {
    {"Formation.DealWithExpeditionInfo", formation.DealWithExpeditionInfo},
    {"Formation.GetAverageSoldierList", formation.GetAverageSoldierList},
    {"Formation.GetFormationHeroData", formation.GetFormationHeroData},
    {"Formation.GetFormationSoldierData", formation.GetFormationSoldierData},
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
