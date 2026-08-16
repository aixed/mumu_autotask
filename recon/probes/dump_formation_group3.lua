local expedition = require("game.helper.ExpeditionHelper")
local formation = require("game.helper.FormationHelper")
local world = require("game.helper.WorldMarchHelper")
local targets = {
    {"Expedition.GetFormationPrefabs", expedition.GetFormationPrefabs},
    {"Formation.GetSoldierDefaultSelection", formation.GetSoldierDefaultSelection},
    {"World.GetAttackMarchType", world.GetAttackMarchType},
    {"World.RequestMarchStartOff", world.RequestMarchStartOff},
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
