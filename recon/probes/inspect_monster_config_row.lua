local config_id = 7100016
local row = package.loaded["game.config.default.world_map_monster"][config_id]
local lines = {"ROW\t" .. type(row) .. "\t" .. tostring(row)}
for key, value in pairs(row or {}) do
    lines[#lines + 1] = table.concat({
        tostring(key), type(value), tostring(value)
    }, "\t")
end
table.sort(lines)
return table.concat(lines, "\n")
