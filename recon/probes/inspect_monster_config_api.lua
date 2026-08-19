local tab = package.loaded["game.config.default.world_map_monster"]
local lines = {"MODULE\t" .. type(tab) .. "\t" .. tostring(tab)}
if type(tab) == "table" then
    for key, value in pairs(tab) do
        lines[#lines + 1] = table.concat({
            "ITEM", tostring(key), type(value), tostring(value)
        }, "\t")
    end
end
table.sort(lines)
return table.concat(lines, "\n"):sub(1, 15000)
